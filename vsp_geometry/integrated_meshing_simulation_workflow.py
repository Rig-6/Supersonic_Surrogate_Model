import importlib
from pathlib import Path
import os
import sys
import ansys.fluent.core as pyfluent
import glob

# Resolve Pathing
SCRIPT_DIR = Path(__file__).parent.resolve()
inp_ffd_dir = Path(str(SCRIPT_DIR / "farfield_optimized_geometries"))
output_dir = Path(str(SCRIPT_DIR / "meshed_output"))
output_dir.mkdir(exist_ok=True)

# Resolve file paths and naming
import_file_name = Path(str(inp_ffd_dir / "cone_L4.0_D1.0_R0.1_ffd.stp"))

os.environ["FLUENT_NO_AUTOMATIC_TRANSCRIPT"] = "1"

# ---STEP 1: Import the geometry into Fluent Meshing---

# Launch Fluent Meshing Session
meshy_session = pyfluent.launch_fluent(mode=pyfluent.FluentMode.MESHING, precision=pyfluent.Precision.DOUBLE, processor_count=6)
watertight = meshy_session.watertight() # Watertight Meshing Mode
import_geometry = watertight.import_geometry # Load Import Geometry Function


'''
meshy_session.workflow.Workflow(WorkflowType="Watertight") # Watertight Meshing Mode
import_geometry = meshy_session.workflow.TaskObject["Import Geometry"] # Import Geometry Function
import_geometry.Arguments.set_state({
    "ImportGeometryControls": {
    "import_geometry_type": "CAD",
    "import_geometry_file_type": "STEP",
    "import_geometry_file_name": str(import_file_name),




    "import_geometry_length_unit": "mm"
    }
})
import_geometry.Execute() # Execute the import geometry function

print(f"---STEP 1: COMPLETED--- Imported geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 2: Generate the Surface Mesh---\
create_surface_mesh = meshy_session.workflow.TaskObject["Generate the Surface Mesh"] # Get the Generate Surface Mesh task object
create_surface_mesh.Arguments.set_state({
    "SurfaceMeshControls": {
        "max_size": 0.3
    }
})
create_surface_mesh.Execute() # Execute the Generate Surface Mesh task
print(create_surface_mesh.cfd_surface_mesh_controls.Arguments) # Print the arguments of the surface mesh controls to verify the settings
print(f"---STEP 2: COMPLETED--- Generated surface mesh for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 3: Describe Geometry---
describe_geometry = meshy_session.workflow.TaskObject["Describe Geometry"] # Get the Describe Geometry task object
describe_geometry.UpdateChildTasks(SetupTypeChanged=False) # Update child tasks with SetupTypeChanged set to False
describe_geometry.Arguments.set_state({
        "SetupType": "The geometry consists of only fluid regions with no voids" # Set Geometry Type
    })
describe_geometry.UpdateChildTasks(SetupTypeChanged=True) # Update the child tasks with SetupTypeChanged set to True
describe_geometry.Execute() # Execute the Describe Geometry task

# --STEP 4: Update regions and boundaries---
update_regions = meshy_session.workflow.TaskObject["Update Regions"] # Get the Update Regions task object
update_regions.Execute() # Execute the Update Regions task
print(update_regions.Argument.get_state()) # Print the state of the Update Regions task arguments
update_bcs = meshy_session.workflow.TaskObject["Update Boundaries"] # Get the Update Boundaries task object
update_bcs.Execute() # Execute the Update Boundaries task

# --STEP 5: Add Boundary Layers---
bl = meshy_session.workflow.TaskObject["Add Boundary Layers"] # Get the Add Boundary Layers task object
bl.Arguments.set_state({
    "AddBoundaryLayers": "no",
    "OffsetMethod": "smooth-transition",
    "NumberOfLayers": 10,
    "TransitionRatio": 0.25,
    "GrowthRate": 1.2,
})
bl.Execute()  # or set Arguments first if you want custom layers 

# --STEP 6: Generate Volume Mesh---
create_vol = meshy_session.workflow.TaskObject["Generate the Volume Mesh"] # Get the Generate Volume Mesh task object
create_vol.Execute() # Execute the Generate Volume Mesh task

# --STEP 7: Save and Export Mesh---
meshy_session.file.write(file_type="mesh", file_name="nose_cone_farfield.msh.h5")
'''

