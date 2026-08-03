# Allow python to find modules located elsewhere within the operating system
import importlib
from pathlib import Path
import os
import sys

# Data formatting through the csv module
import csv

# The numpy module for mathematical operations
import numpy as np

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

lengths = np.linspace(50, 150, 3)
diameters = np.linspace(5, 15, 3)
nose_radii = np.linspace(1.0, 5.0, 3)

iteration_total = len(lengths) * len(diameters) * len(nose_radii)

print(f"Generating {iteration_total} nose cones with parameter combinations")

# --> Section 2: Create the CSV file to store the parameter combinations

geom_dir = Path("C:\\Users\\s3nor\\Documents\\NoseConeProML\\vsp_geometry\\generated_geometries\\")
geom_dir.mkdir(exist_ok=True)

comb_file_name = geom_dir / "parameter_combinations.csv"

with open(comb_file_name, mode='w', newline='') as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(['Length', 'Diameter', 'Nose_Radius', 'Fineness_Ratio', 'STL_File_Name'])




# --> Section 3: Generate the geometries and save them as STL files

iteration = 0

for L in lengths:
    for D in diameters:
        for R in nose_radii:
            iteration += 1
            
            # Clean OpenVSP Workspace
            vsp.ClearVSPModel()

            # Create geometry
            nose_cone_id = vsp.AddGeom("POD")
            fineness = L/D

            # Modify geometry parameters
            vsp.SetParmVal(nose_cone_id, "Length", "Design", L)

            # Bluntness is controlled by the fineness ratio, which is the length divided by the diameter
            vsp.SetParmVal(nose_cone_id, "FineRatio", "Design", fineness)

            # Smooth the mesh by increasing the number of circumferential and longitudinal cuts
            vsp.SetParmVal(nose_cone_id, "Tess_U", "Shape", 81) # Smooths around the circle
            vsp.SetParmVal(nose_cone_id, "Tess_W", "Shape", 81) # Smooths along the length
            vsp.Update()

            # Generate the filename 
            filename = f"cone_L{L:.1f}_D{D:.1f}_R{R:.1f}.stp"

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
            print(f"Executing Trimming Analysis for iteration {iteration}...")
            results_id = vsp.ExecAnalysis(analysis_name)
            vsp.Update()

            # Generate computational geometry (mesh) and export as STL
            #vsp.ComputeCompGeom(vsp.SET_ALL, False, vsp.EXPORT_STEP)
            #vsp.ExportFile(str(filename), vsp.SET_ALL, vsp.EXPORT_STEP)


            # Add the data to the csv file
            with open(comb_file_name, mode='a', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([L, D, R, fineness, filename])

            print(f"[{iteration}/{iteration_total}] Saved: {filename}")
            



# Configure the parameters for the trimmed surfaces
'''vsp.SetIntAnalysisInput(analysis_name, "ExportType", [vsp.EXPORT_STEP])
vsp.SetDoubleAnalysisInput(analysis_name, "Tolerance", [1e-6])
vsp.SetStringAnalysisInput(analysis_name, "FileName", ["trimmed_model.vsp3"])

print("Listing all Analysis Names: ")
for name in vsp.ListAnalysis():
    print(name)

analysis_name = "SurfaceIntersection"

input_names = vsp.GetAnalysisInputNames(analysis_name)

for name in input_names:
    print(f"Input Name: {name}")
    input_type = vsp.GetAnalysisInputType(analysis_name, name)
    print(f"Input Type: {input_type}")'''
