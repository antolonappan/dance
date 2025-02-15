from numpy import arange
import sys
sys.path.append('../')

from dance.qe import Reconstruct
from dance import mpi

basedir = '/mnt/sdceph/users/alonappan/DANCE'
recon = Reconstruct(basedir,2048,"aniso",Acb=1e-6,lmin_ivf=2,lmax_ivf=4096,lmax_qlm=4096,qe_key="a_p")


start_idx = 0
end_idx = 300

jobs = arange(start_idx,end_idx)

mpi.barrier()
for i in jobs[mpi.rank::mpi.size]:
    print(f"Rank {mpi.rank} is working on job {i}")
    qlm = recon.get_qlm(i)
    n0 = recon.get_n0(i)
    del (qlm,n0)
mpi.barrier()