"""Continue the same isolated full-cluster selection experiment for C11..C30."""
import sys
from pathlib import Path

import c03_c10_selection as trial

BASE=Path(__file__).resolve().parents[1]
trial.CLUSTERS=[f'C{i:02d}' for i in range(11,31)]
trial.WORK=BASE/'work/c11-c30-allarticles-trial'
trial.OUT=BASE/'outputs/C11-C30-allarticles-selection-20261015'
trial.WORK.mkdir(exist_ok=True)
trial.OUT.mkdir(exist_ok=True)

if __name__=='__main__':
    {'prepare':trial.prepare,'call':trial.call_all}[sys.argv[1]]()
