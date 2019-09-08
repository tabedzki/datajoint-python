from nose.tools import assert_true, assert_false, assert_equal, assert_not_equal, raises
import datajoint as dj
from . import PREFIX, CONN_INFO

schema = dj.schema(PREFIX + '_dimensionless', locals(), connection=dj.conn(**CONN_INFO))


@schema
class Dimensionless(dj.Manual):
    definition = """
    ---
    fact : varchar(120)   #  a singular fact
    """


@schema
class DimensionlessChild(dj.Manual):
    definition = """
    -> Dimensionless
    ---
    today : date
    """


@raises(dj.DataJointError)
def test_fail_dependent_insert():
    DimensionlessChild.insert1(["2019-09-09"])


def test_dependent_insert():
    Dimensionless.insert1(["wolves don't hypernate"])
    DimensionlessChild.insert1(["2019-09-09"])