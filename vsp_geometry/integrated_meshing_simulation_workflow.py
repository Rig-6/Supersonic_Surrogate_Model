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
meshy_session = pyfluent.launch_fluent(mode=pyfluent.FluentMode.MESHING, precision=pyfluent.Precision.DOUBLE, processor_count=6, show_gui=True)
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
    r"OldRegionNameList": [r'fluid', r'open-cascade-step-translator-7.8-1-solid'],
    r"OldRegionTypeList": [r'fluid', r'fluid'],
    r"RegionNameList": [r'cone', r'farfield_volume'],
    r"RegionTypeList": [r'dead', r'fluid'],
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

# Insert Improve Volume Mesh as a follow-up task
improve_vol = volume_mesh.InsertNextTask(CommandName="ImproveVolumeMesh")
improve_vol.Arguments.set_state({
    "CellQualityLimit": 0.15,   # raise the minimum orthogonal quality target
})
improve_vol.Execute()
print(f"---STEP 6: COMPLETED--- Created volume mesh for geometry: {import_file_name} into Fluent Meshing session.")



# --STEP 7: Save and Export Mesh---
meshy_session.tui.file.write_mesh(f"{import_file_name}.msh.h5") # Save the mesh to a file
print(f"---STEP 7: COMPLETED--- Saved and exported mesh for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 8: Switch to Solver Session and check mesh quality---
solvy_session = meshy_session.switch_to_solver() # Switch to solver session

solvy_session.settings.mesh.check() # Check the mesh quality
print(f"---STEP 8: COMPLETED--- Switched to solver session and checked mesh quality for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 9: Define model, materials, and boundary conditions and other settings---
viscous = solvy_session.setup.models.viscous # Load the Viscous Model function
viscous.model = "k-omega" # Set the viscous model to k-omega
viscous.k_omega_model = "sst" # Set the k-omega model to sst

air = solvy_session.settings.setup.materials.fluid["air"] # Load the air material properties
air.density.option = "ideal-gas" # Set the density option for air to ideal gas
air.viscosity.option = "sutherland" # Set the viscosity option for air to sutherland
air.viscosity.sutherland.option = "three-coefficient-method" # Set the sutherland option for air to three coefficient method
air.viscosity.sutherland.reference_viscosity = 1.716e-05 # Set the reference viscosity for air to 1.716e-05
air.viscosity.sutherland.reference_temperature = 273.11 # Set the reference temperature for air to 273.11
air.viscosity.sutherland.effective_temperature = 110.56 # Set the effective temperature for air to 110.56

bc = solvy_session.settings.setup.boundary_conditions # Load the boundary conditions
pressure_farfield = bc.pressure_far_field["farfield_volume"] # Load the pressure far field boundary condition
pressure_farfield.momentum.gauge_pressure = 0 # Set the gauge pressure for the pressure far field to 0
pressure_farfield.momentum.mach_number = 2.0 # Set the mach number for the pressure far field to 2.0
pressure_farfield.thermal.temperature = 288.15 # Set the temperature for the pressure far field to 288.15
pressure_farfield.momentum.flow_direction[0] = 1.0 # Set the flow direction for the pressure far field to 1.0 in the x-direction
# pressure_farfield.turbulence.turbulent_intensity = 0.05
# pressure_farfield.turbulence.turbulent_viscosity_ratio = 10

solvy_session.settings.setup.general.operating_conditions.operating_pressure = 80600
solvy_session.settings.setup.general.operating_conditions.operating_pressure = 22632 

solvy_session.settings.solution.initialization.hybrid_initialize()
# solvy_session.settings.file.write(
#     file_name="external_compressible.cas.h5", file_type="case"
# )

solvy_session.settings.solution.report_definitions.drag["cd_monitor"] = {
    "zones": ["fluid"],   # use your auto-detected cone wall zone
    "force_vector": [1, 0, 0],           # flow direction
}


print(f"---STEP 9: COMPLETED--- Defined model, materials, and boundary conditions and other settings for geometry: {import_file_name} into Fluent Meshing session.")

# ---STEP 10: Run the calculation and write results---
solvy_session.settings.solution.run_calculation.iterate(iter_count=25)

cd_value = solvy_session.settings.solution.report_definitions.compute(report_defs=["cd_monitor"])
solvy_session.settings.file.write(file_type="case", file_name="external_compressible.cas.h5")