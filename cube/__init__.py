"""Rebirth V5 application package."""

import os


# Keep dataframe/BLAS work on one compute thread by default. Request threads
# remain available for progress and network I/O. Deployments can opt into more.
for _numeric_thread_variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[_numeric_thread_variable] = os.getenv("CUBE_NUMERIC_THREADS", "1")

__version__ = "5.0.0"

__all__ = ["__version__"]
