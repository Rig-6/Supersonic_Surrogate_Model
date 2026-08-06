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
import_file_name = str(inp_ffd_dir / "cone_L12.0_D2.0_R0.1_ffd.stp")



os.environ["FLUENT_NO_AUTOMATIC_TRANSCRIPT"] = "1"

# ---STEP 1: Import the geometry into Fluent Meshing---

# Launch Fluent Meshing Session
meshy_session = pyfluent.launch_fluent(mode=pyfluent.FluentMode.MESHING, precision=pyfluent.Precision.DOUBLE, processor_count=6, show_gui=False)
watertight = meshy_session.watertight() # Watertight Meshing Mode
import_geometry = watertight.import_geometry # Load Import Geometry Function
import_geometry.file_name = import_file_name # Set the file name for the geometry to be imported
import_geometry.length_unit = "mm" # Set the length unit for the geometry
import_geometry() # Execute the import geometry function
print(f"---STEP 1: COMPLETED--- Imported geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 2: Generate the Surface Mesh---
surf_mesh = watertight.create_surface_mesh # Load the Generate Surface Mesh function
surf_mesh.cfd_surface_mesh_controls.min_size = 0.3 # Set the min size for the surface mesh
surf_mesh() # Execute the Generate Surface Mesh function
print(f"---STEP 2: COMPLETED--- Generated surface mesh for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 3: Describe Geometry---
describe_geometry = watertight.describe_geometry # Load the Describe Geometry function
describe_geometry.update_child_tasks(setup_type_changed=False) # Update child tasks with SetupTypeChanged set to False
# describe_geometry.setup_type.set_state("The geometry consists of both fluid and solid regions and/or voids")
describe_geometry.setup_type.set_state("The geometry consists of only fluid regions with no voids") # Set the setup type for the geometry
describe_geometry.update_child_tasks(setup_type_changed=True) # Update the child tasks with SetupTypeChanged set to True
describe_geometry() # Execute the Describe Geometry function
print(f"---STEP 3: COMPLETED--- Described geometry for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 4: Update boundaries and regions---
update_regions = meshy_session.workflow.TaskObject["Update Regions"]
# update_regions.Execute()


update_regions.Arguments.set_state({
    r"OldRegionNameList": [r'fluid'],
    r"OldRegionTypeList": [r'fluid'],
    r"RegionNameList": [r'fluid'],
    r"RegionTypeList": [r'dead'],
})

update_regions.Execute()

update_boundaries = watertight.update_boundaries # Load the Update Boundaries function
# update_boundaries.boundary_zone_list = ["wall-inlet"]
# update_boundaries.boundary_label_list = ["wall-inlet"]
# update_boundaries.boundary_label_list = ["wall"]
# update_boundaries.old_boundary_label_list = ["wall-inlet"]
# update_boundaries.old_boundary_label_type_list = ["velocity-inlet"]
update_boundaries() # Execute the Update Boundaries function
print(f"---STEP 4: COMPLETED--- Updated regions and boundaries for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 5: Add boundary Layers---
add_bl = watertight.add_boundary_layer # Load the Add Boundary Layers function
add_bl.control_name = "smooth-transition_1" # Set the control name for the boundary layers to smooth transition
add_bl.number_of_layers = 10 # Set the number of layers for the boundary layers
add_bl.growth_rate = 1.2 # Set the growth rate for the boundary layers
add_bl.insert_compound_child_task() # Insert the compound child task for the Add Boundary Layers function
watertight.add_boundary_layer_child_1() # Execute the Add Boundary Layers 
print(f"---STEP 5: COMPLETED--- Added boundary layers for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 6: Update regions and boundaries---
volume_mesh = watertight.create_volume_mesh # Load the Create Volume Mesh function
volume_mesh.max_size = 0.3 # Set the maximum size for the volume mesh
volume_mesh.volume_fill_type = "poly-hexcore" # Set the volume fill type to polyhexcore
volume_mesh() # Execute the Create Volume Mesh function
print(f"---STEP 6: COMPLETED--- Created volume mesh for geometry: {import_file_name} into Fluent Meshing session.")

# --STEP 7: Save and Export Mesh---
meshy_session.tui.file.write_mesh("nose_cone_test7_farfield.msh.h5") # Save the mesh to a file
print(f"---STEP 7: COMPLETED--- Saved and exported mesh for geometry: {import_file_name} into Fluent Meshing session.")


'''
solvy_session = messhing.session.switch_to_solver() # Switch to solver session



'''