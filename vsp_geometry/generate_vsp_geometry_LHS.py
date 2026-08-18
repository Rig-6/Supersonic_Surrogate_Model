# Allow python to find modules located elsewhere within the operating system
import importlib
from pathlib import Path
import os
import sys
import glob

# Scipy package for LHS feature
import scipy

# Data formatting through the csv module
import csv

# The numpy module for mathematical operations
import numpy as np

#Imports Quasi Monte Carlo sampling for Latin Hypercube Sampling
from scipy.stats import qmc

import hashlib

def run_id(index: int, *params: float) -> str:
    """Generates a unique run ID based on the index and parameters."""
    payload = "|".join(f"{p:.10g}" for p in params)
    digest = hashlib.sha1(payload.encode()).hexdigest()[:8]
    return f"{index:03d}_{digest}"
    

sampler = qmc.LatinHypercube(d=2, seed=42)  # 2 parameters: fineness, diameter

# The vsp module for generating the geometries
def add_openvsp_paths() -> None:
    configured_root = os.environ.get("OPENVSP_PYTHON_PATH")
    openvsp_root = Path(configured_root) if configured_root else Path(r"C:\OpenVSP\python")
    install_root = openvsp_root.parent

    if hasattr(os, "add_dll_directory"):
        for dll_root in (install_root, openvsp_root):
            if dll_root.exists():
                os.add_dll_directory(str(dll_root))

    package_roots = [
        openvsp_root / "openvsp",
        openvsp_root / "degen_geom",
        openvsp_root / "utilities",
        openvsp_root / "openvsp_config",
    ]

    for package_root in package_roots:
        if package_root.exists():
            package_root_text = str(package_root)
            if package_root_text not in sys.path:
                sys.path.insert(0, package_root_text)


def require_supported_python_version() -> None:
    if sys.version_info[:2] != (3, 13):
        raise SystemExit(
            f"OpenVSP's bundled Python environment targets Python 3.13, but this interpreter is {sys.version_info.major}.{sys.version_info.minor}. Create or activate the conda env from C:\\OpenVSP\\python\\environment.yml before running this script."
        )


require_supported_python_version()
add_openvsp_paths()


def load_vsp_module():
    for module_name in ("openvsp", "vsp"):
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        except ImportError:
            continue

    raise ModuleNotFoundError(
        "Could not import OpenVSP. Set OPENVSP_PYTHON_PATH to the folder that contains the OpenVSP Python bindings, or install OpenVSP to C:\\OpenVSP\\python."
    )


vsp = load_vsp_module()

# --> Section 1: Generate parameter limit lists

SIZE_FACTOR = 1  # Scale factor to reduce the size of the generated geometries

lower_bounds = [4, 1 * SIZE_FACTOR]
upper_bounds = [8, 3 * SIZE_FACTOR]

# --> Section 2: Create the CSV file to store the parameter combinations

# Pathing sync stuff

# Grab absolute path to current script
SCRIPT_PATH = Path(__file__).resolve().parent

geom_dir = Path(SCRIPT_PATH / "generated_geometries")
geom_dir.mkdir(exist_ok=True)

comb_file_name = geom_dir / "parameter_combinations.csv"

with open(comb_file_name, mode='w', newline='') as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(['Run_ID','Length', 'Diameter',  'Fineness_Ratio', 'STEP_File_Name'])

# --> Section 3: Generate the geometries and save them as STL files
iteration_total = 20 # Total number of samples to generate
samples = sampler.random(n=iteration_total) # Generates iteration_total amount samples, samples have 3 parameters (fineness, diameter, nose radius)
iteration = 0
print(f"Generating {iteration_total} nose cones with parameter combinations")

samples = qmc.scale(samples, lower_bounds, upper_bounds) #fits sample parameters of fineness, diameter, and nose radius to the upper and lower bounds

for sample in samples:
            F, D = sample  # Unpack the parameters from the sample    
            R = D / 2  # Calculate radius from diameter
            iteration += 1
            L = F * R  # Calculate length based on fineness ratio and radius (normally diameter but not for OpenVSP I guess)
            
            # Clean OpenVSP Workspace
            vsp.ClearVSPModel()

            # Create geometry
            nose_cone_id = vsp.AddGeom("POD")

            # Modify geometry parameters
            vsp.SetParmVal(nose_cone_id, "Length", "Design", L)

            # Bluntness is controlled by the fineness ratio, which is the length divided by the radius (normally diameter but not for OpenVSP I guess)
            vsp.SetParmVal(nose_cone_id, "FineRatio", "Design", F)

            # Smooth the mesh by increasing the number of circumferential and longitudinal cuts (Doesn't matter for STEP files)
            # vsp.SetParmVal(nose_cone_id, "Tess_U", "Shape", 81) # Smooths around the circle
            # vsp.SetParmVal(nose_cone_id, "Tess_W", "Shape", 81) # Smooths along the length
            # vsp.Update()

            # Generate the filename 
            rid = run_id(iteration, L, D)
            filename = f"cone_{rid}_L{L:.2f}_R{R:.2f}.stp"

            # Resolve file path to geometry directory

            filename = geom_dir / filename

            # Set up the analysis for trimmed surfaces
            analysis_name = "SurfaceIntersection"
            vsp.SetAnalysisInputDefaults(analysis_name) # Start with input defaults for the analysis
            vsp.SetIntAnalysisInput(analysis_name, "SelectedSetIndex", [vsp.SET_ALL]) # Select all geometries for analysis
            vsp.SetIntAnalysisInput(analysis_name, "STEPFileFlag", [1])  # Enable STEP file output
            vsp.SetDoubleAnalysisInput(analysis_name, "STEPTol", [1e-6]) # Set the tolerance for the STEP file output
            vsp.SetDoubleAnalysisInput(analysis_name, "RelCurveTol", [1e-6]) # Set the chord tolerance for the STEP file output
            vsp.SetStringAnalysisInput(analysis_name, "STEPFileName", [str(filename)]) # Set the output filename for the STEP file
            vsp.SetIntAnalysisInput(analysis_name, "STEPRepresentation", [vsp.STEP_BREP]) # Set the representation for the STEP file output to BREP so its a solid and not a surface

            # Disable other file outputs to avoid unnecessary files
            vsp.SetIntAnalysisInput(analysis_name, "P3DFileFlag", [0])  # Disable P3D file output
            vsp.SetIntAnalysisInput(analysis_name, "SRFFileFlag", [0])  # Disable SRF file output
            vsp.SetIntAnalysisInput(analysis_name, "P3DFileFlag", [0])  # Disable P3D file output
            vsp.SetIntAnalysisInput(analysis_name, "ExportRawFlag", [0])  # Disable raw file output
            vsp.SetIntAnalysisInput(analysis_name, "IGESFileFlag", [0]) # Set the export type for the analysis
            vsp.SetIntAnalysisInput(analysis_name, "CURVFileFlag", [0]) # Set the export type for the analysis

            # Finished setting up the analysis, now update the model to apply the changes
            vsp.Update()
            
            # Set the output filename for the file
            #vsp.SetStringAnalysisInput(analysis_name, "FileName", str(filename))
            
            # Start Trimming Analysis
            # print(sample)
            print(f"Executing Trimming Analysis for iteration {iteration} with LHS...")
            results_id = vsp.ExecAnalysis(analysis_name)
            vsp.Update()

            # Generate computational geometry (mesh) and export as STL
            #vsp.ComputeCompGeom(vsp.SET_ALL, False, vsp.EXPORT_STEP)
            #vsp.ExportFile(str(filename), vsp.SET_ALL, vsp.EXPORT_STEP)


            # Add the data to the csv file
            with open(comb_file_name, mode='a', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([rid, L, D, F, filename])

            print(f"[{iteration}/{iteration_total}] Saved: {filename}")


# Clean up backup files generated by OpenVSP

for bak_file in glob.glob("*.stp.bak"):
    try:
        os.remove(bak_file)
    except OSError:
        pass

print("Finished generating geometries and saving parameter combinations to CSV and removing backup files.")
