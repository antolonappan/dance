from numpy import arange
import sys
sys.path.append('../')

from dance.simulations import Sky
from dance import mpi

basedir = '/mnt/sdceph/users/alonappan/DANCE'
sky = Sky(basedir,2048,1,'iso',beta=0.35)

start_idx = 1
end_idx = 100

jobs = arange(start_idx,end_idx)

mpi.barrier()
for i in jobs[mpi.rank::mpi.size]:
    print(f"Rank {mpi.rank} is working on job {i}")
    qu = sky.get_EB(i)
    del qu
mpi.barrier()