import sys
from functools import partial
import warnings
import pandas
import re
import os
import numpy as np
import uuid
from . import blob, attach, hash
from .errors import DataJointError
from .settings import config

if sys.version_info[1] < 6:
    from collections import OrderedDict
else:
    # use dict in Python 3.6+ -- They are already ordered and look nicer
    OrderedDict = dict


class key:
    """
    object that allows requesting the primary key as an argument in expression.fetch()
    The string "KEY" can be used instead of the class key
    """
    pass


def is_key(attr):
    return attr is key or attr == 'KEY'


def to_dicts(recarray):
    """convert record array to a dictionaries"""
    for rec in recarray:
        yield OrderedDict(zip(recarray.dtype.names, rec.tolist()))


def _get(connection, attr, data, squeeze, download_path):
    """
    This function is called for every attribute 

    :param connection: a dj.Connection object
    :param attr: attribute name from the table's heading
    :param data: literal value fetched from the table
    :param squeeze: if True squeeze blobs
    :param download_path: for fetches that download data, e.g. attachments
    :return: unpacked data
    """

    if data is None:
        return 

    extern = connection.schemas[attr.database].external[attr.store] if attr.is_external else None

    if attr.is_attachment:
        # Steps: 
        # 1. peek the filename from the blob without downloading remote
        # 2. check if the file already exists at download_path, verify checksum
        # 3. if exists and checksum passes then return the local filepath
        # 4. Otherwise, download the remote file and return the new filepath
        peek, size = extern.peek(uuid.UUID(bytes=data)) if attr.is_external else (data, len(data))
        assert size is not None 
        filename = peek.split(b"\0", 1)[0].decode()
        size -= len(filename)
        filepath = os.path.join(download_path, filename)
        if os.path.isfile(filepath) and size == os.path.getsize(filepath):
            local_checksum = hash.uuid_from_file(filepath) 
            remote_checksum = (uuid.UUID(bytes=data)
                    if attr.is_external else hash.uuid_from_buffer(data))
            if local_checksum == remote_checksum: 
                return filepath  # the existing file is okay
        # Download remote attachment
        if attr.is_external:
            data = extern.get(uuid.UUID(bytes=data))
        return attach.save(data, download_path)  # download file from remote store

    return uuid.UUID(bytes=data) if attr.uuid else (
            blob.unpack(extern.get(uuid.UUID(bytes=data)) if attr.is_external else data, squeeze=squeeze) 
            if attr.is_blob else data)


def _flatten_attribute_list(primary_key, attrs):
    """
    :param primary_key: list of attributes in primary key
    :param attrs: list of attribute names, which may include "KEY", "KEY DESC" or "KEY ASC"
    :return: generator of attributes where "KEY" is replaces with its component attributes
    """
    for a in attrs:
        if re.match(r'^\s*KEY(\s+[aA][Ss][Cc])?\s*$', a):
            yield from primary_key
        elif re.match(r'^\s*KEY\s+[Dd][Ee][Ss][Cc]\s*$', a):
            yield from (q + ' DESC' for q in primary_key)
        else:
            yield a


class Fetch:
    """
    A fetch object that handles retrieving elements from the table expression.
    :param expression: the table expression to fetch from.
    """

    def __init__(self, expression):
        self._expression = expression

    def __call__(self, *attrs, offset=None, limit=None, order_by=None, format=None, as_dict=None,
                 squeeze=False, download_path='.'):
        """
        Fetches the expression results from the database into an np.array or list of dictionaries and unpacks blob attributes.

        :param attrs: zero or more attributes to fetch. If not provided, the call will return
        all attributes of this relation. If provided, returns tuples with an entry for each attribute.
        :param offset: the number of tuples to skip in the returned result
        :param limit: the maximum number of tuples to return
        :param order_by: a single attribute or the list of attributes to order the results.
                No ordering should be assumed if order_by=None.
                To reverse the order, add DESC to the attribute name or names: e.g. ("age DESC", "frequency")
                To order by primary key, use "KEY" or "KEY DESC"
        :param format: Effective when as_dict=None and when attrs is empty
                None: default from config['fetch_format'] or 'array' if not configured
                "array": use numpy.key_array
                "frame": output pandas.DataFrame. .
        :param as_dict: returns a list of dictionaries instead of a record array.
                Defaults to False for .fetch() and to True for .fetch('KEY')
        :param squeeze:  if True, remove extra dimensions from arrays
        :param download_path: for fetches that download data, e.g. attachments
        :return: the contents of the relation in the form of a structured numpy.array or a dict list
        """

        if order_by is not None:
            # if 'order_by' passed in a string, make into list
            if isinstance(order_by, str):
                order_by = [order_by]
            # expand "KEY" or "KEY DESC"
            order_by = list(_flatten_attribute_list(self._expression.primary_key, order_by))

        # as_dict defaults to False for fetch() and to True for fetch('KEY', ...)
        if as_dict is None:
            as_dict = bool(attrs)
        # format should not be specified with attrs or is_dict=True
        if format is not None and (as_dict or attrs):
            raise DataJointError('Cannot specify output format when as_dict=True or '
                                 'when attributes are selected to be fetched separately.')
        if format not in {None, "array", "frame"}:
            raise DataJointError('Fetch output format must be in {{"array", "frame"}} but "{}" was given'.format(format))

        if not (attrs or as_dict) and format is None:
            format = config['fetch_format']  # default to array
            if format not in {"array", "frame"}:
                raise DataJointError('Invalid entry "{}" in datajoint.config["fetch_format"]: use "array" or "frame"'.format(format))

        if limit is None and offset is not None:
            warnings.warn('Offset set, but no limit. Setting limit to a large number. '
                          'Consider setting a limit explicitly.')
            limit = 2 * len(self._expression)

        get = partial(_get, self._expression.connection, squeeze=squeeze, download_path=download_path)
        if not attrs:
            # fetch all attributes as a numpy.record_array or pandas.DataFrame
            cur = self._expression.cursor(as_dict=as_dict, limit=limit, offset=offset, order_by=order_by)
            heading = self._expression.heading
            if as_dict:
                ret = [OrderedDict((name, get(heading[name], d[name])) for name in heading.names) for d in cur]
            else:
                ret = list(cur.fetchall())
                ret = np.array(ret, dtype=heading.as_dtype)
                for name in heading:
                    ret[name] = list(map(partial(get, heading[name]), ret[name]))
                if format == "frame":
                    ret = pandas.DataFrame(ret).set_index(heading.primary_key)
        else:  # if list of attributes provided
            attributes = [a for a in attrs if not is_key(a)]
            result = self._expression.proj(*attributes).fetch(
                offset=offset, limit=limit, order_by=order_by,
                as_dict=False, squeeze=squeeze, download_path=download_path)
            return_values = [
                list((to_dicts if as_dict else lambda x: x)(result[self._expression.primary_key])) if is_key(attribute)
                else result[attribute] for attribute in attrs]
            ret = return_values[0] if len(attrs) == 1 else return_values

        return ret


class Fetch1:
    """
    Fetch object for fetching exactly one row.
    :param relation: relation the fetch object fetches data from
    """

    def __init__(self, relation):
        self._expression = relation

    def __call__(self, *attrs, squeeze=False, download_path='.'):
        """
        Fetches the expression results from the database when the expression is known to yield only one entry.

        If no attributes are specified, returns the result as a dict.
        If attributes are specified returns the corresponding results as a tuple.

        Examples:
        d = rel.fetch1()   # as a dictionary
        a, b = rel.fetch1('a', 'b')   # as a tuple

        :params *attrs: attributes to return when expanding into a tuple. If empty, the return result is a dict
        :param squeeze:  When true, remove extra dimensions from arrays in attributes
        :param download_path: for fetches that download data, e.g. attachments
        :return: the one tuple in the relation in the form of a dict
        """
        heading = self._expression.heading

        if not attrs:  # fetch all attributes, return as ordered dict
            cur = self._expression.cursor(as_dict=True)
            ret = cur.fetchone()
            if not ret or cur.fetchone():
                raise DataJointError('fetch1 should only be used for relations with exactly one tuple')
            ret = OrderedDict((name, _get(self._expression.connection, heading[name], ret[name],
                                          squeeze=squeeze, download_path=download_path))
                              for name in heading.names)
        else:  # fetch some attributes, return as tuple
            attributes = [a for a in attrs if not is_key(a)]
            result = self._expression.proj(*attributes).fetch(squeeze=squeeze, download_path=download_path)
            if len(result) != 1:
                raise DataJointError('fetch1 should only return one tuple. %d tuples were found' % len(result))
            return_values = tuple(
                next(to_dicts(result[self._expression.primary_key])) if is_key(attribute) else result[attribute][0]
                for attribute in attrs)
            ret = return_values[0] if len(attrs) == 1 else return_values

        return ret
