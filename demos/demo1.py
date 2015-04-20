# -*- coding: utf-8 -*-
"""
Created on Tue Aug 26 17:42:52 2014

@author: dimitri
"""

import datajoint as dj

print("Welcome to the database 'demo1'")

conn = dj.conn()   # connect to database; conn must be defined in module namespace
conn.bind(module=__name__, dbname='dj_test')  # bind this module to the database



class Subject(dj.Base):
    _table_def = """
    demo1.Subject (manual)     # Basic subject info

    subject_id       : int     # internal subject id
    ---
    real_id                     :  varchar(40)    #  real-world name
    species = "mouse"           : enum('mouse', 'monkey', 'human')   # species
    date_of_birth=null          : date                          # animal's date of birth
    sex="unknown"               : enum('M','F','unknown')       #
    caretaker="Unknown"         : varchar(20)                   # person responsible for working with this subject
    animal_notes=""             : varchar(4096)                 # strain, genetic manipulations, etc
    """

class Exp2(dj.Base):
    pass

class Experiment(dj.Base):
    _table_def = """
    demo1.Experiment (manual)     # Basic subject info

    -> demo1.Subject
    experiment          : smallint   # experiment number for this subject
    ---
    experiment_date                 : date        # experiment start date
    experiment_notes=""             : varchar(4096)
    experiment_ts=CURRENT_TIMESTAMP : timestamp   # automatic timestamp
    """


class TwoPhotonSession(dj.Base):
    _table_def = """
    demo1.TwoPhotonSession (manual)   # a two-photon imaging session

    -> demo1.Experiment
    tp_session : tinyint  # two-photon session within this experiment
    ----
    setup      : tinyint   # experimental setup
    lens       : tinyint   # lens e.g.: 10x, 20x. 25x, 60x
    """
class EphysSetup(dj.Base):
    _table_def = """
    demo1.EphysSetup (manual) # Ephys setup
    setup_id    : tinyint # unique seutp id
    """

class EphysExperiment(dj.Base):
    _table_def = """
    demo1.EphysExperiment (manual) # Ephys experiment
    -> demo1.Subject
    -> demo1.EphysSetup
    """