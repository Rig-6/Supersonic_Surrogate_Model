This is a project meant to create a surrogate machine learning model that evaluates the aerodynamic qualities of geometric shapes.

## OpenVSP setup

The OpenVSP Python bindings are not installed through `pip` in this repo. The bundled Python environment targets Python 3.13, so the system Python 3.14 in this workspace will not load `_vsp.pyd`.

On Windows, download and unzip OpenVSP, then either:

1. Place it at `C:\OpenVSP\python`, or
2. Set `OPENVSP_PYTHON_PATH` to the folder that contains the `openvsp`, `degen_geom`, `utilities`, and `openvsp_config` folders.

The safest setup is to create the conda environment shipped with OpenVSP:

1. Open a conda-capable shell.
2. Run `conda env create -f C:\OpenVSP\python\environment.yml`.
3. Run `conda activate vsppytools`.
4. Run `python test_vsp.py` from that environment.

After that, run `python test_vsp.py` to verify the import and connection.
