import csv
import importlib
from pathlib import Path
import os
import sys
import ansys.fluent.core as pyfluent
import glob
import math


# Resolve Pathing
SCRIPT_DIR = Path(__file__).parent.resolve() # Grabs script directory path
inp_ffd_dir = Path(str(SCRIPT_DIR / "farfield_optimized_geometries"))
msh_output_dir = Path(str(SCRIPT_DIR / "meshed_output"))  # Path to the mesh output directory
msh_output_dir.mkdir(exist_ok=True) # Creates the mesh output directory if it doesn't exist
cas_output_dir = Path(str(SCRIPT_DIR / "simulated_output")) # Path to the simulated output directory
cas_output_dir.mkdir(exist_ok=True) # Creates the simulated output directory if it doesn't exist

# Grab all the .stp files in the farfield_optimized_geometries directory
stp_files = sorted(glob.glob(str(inp_ffd_dir / "*.stp")))

# Make the CSV file to store the sim results
with open(f'{cas_output_dir / "simulated.csv"}', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['File_Name', 'Drag_Coefficient'])

for stp_file in stp_files:
    basename = os.path.splitext(os.path.basename(stp_file))[0] # Get the base name of the .stp file without extension
    import_file_name = str(stp_file) # Create the full path to the .stp file
    msh_output_file_name = str(msh_output_dir / f"{basename}_sim") # Create the path to the mesh output directory
    cas_output_file_name = str(cas_output_dir / f"{basename}_sim")

    # Resolve file paths and naming
    # import_file_name = str(inp_ffd_dir / "cone_L24.0_D3.0_R0.1_ffd.stp")



    os.environ["FLUENT_NO_AUTOMATIC_TRANSCRIPT"] = "1"

    # ---STEP 1: Import the geometry into Fluent Meshing---
    meshy_session = pyfluent.launch_fluent(mode=pyfluent.FluentMode.MESHING, precision=pyfluent.Precision.DOUBLE, processor_count=12, show_gui=True) # Launch Fluent Meshing Session
    watertight = meshy_session.watertight() # Watertight Meshing Mode
    import_geometry = watertight.import_geometry # Load Import Geometry Function
    import_geometry.file_name = import_file_name # Set the file name for the geometry to be imported
    import_geometry.length_unit = "mm" # Set the length unit for the geometry
    import_geometry() # Execute the import geometry function
    print(f"---STEP 1: COMPLETED--- Imported geometry: {import_file_name} into Fluent Meshing session.")

    face_zones = meshy_session.scheme_eval.scheme_eval(
        '(tgapi-util-convert-zone-ids-to-name-strings (get-face-zones-of-filter "*"))'
    )

    solid_face_zone = face_zones[0]
    print(f"Solid face zone: {solid_face_zone}")

    add_local_sizing = meshy_session.workflow.TaskObject["Add Local Sizing"] # Load the Add Local Sizing function
    meshy_session.tui.boundary.separate.sep_face_zone_by_angle([solid_face_zone], 40) # Separate the face zone by angle

    separated_zones = meshy_session.scheme_eval.scheme_eval(
        '(tgapi-util-convert-zone-ids-to-name-strings (get-face-zones-of-filter "*"))'
    )

    zone_id = meshy_session.scheme_eval.scheme_eval(
        "(get-face-zone-at-location '(2.0 0.15 0.0))"  # Edit with the correct coordinates for your geometry to get the zone ID of the cone wall face
    )
    cone_wall_zone = meshy_session.scheme_eval.scheme_eval(
        f"(tgapi-util-convert-zone-ids-to-name-strings (list {zone_id}))"
    )[0]
    print(f"Cone wall zone: {cone_wall_zone}")

    add_local_sizing.Arguments.set_state({
        r'AddChild': r'yes',
        r'BOICellsPerGap': 1,
        r'BOIControlName': r'curvature',
        r'BOICurvatureNormalAngle': 18,
        r'BOIExecution': r'Curvature',
        r'BOIFaceZoneList': [cone_wall_zone],
        r'BOIGrowthRate': 1.2,
        r'BOIMaxSize': 10,
        r'BOIMinSize': 0.05,
        r'BOIZoneorLabel': r'zone',
    })
    add_local_sizing.AddChildAndUpdate(DeferUpdate=False) # Add the local sizing and update the child tasks

    # ---STEP 2: Generate the Surface Mesh---
    surf_mesh = meshy_session.workflow.TaskObject["Generate the Surface Mesh"] # Load the Generate Surface Mesh function
    surf_mesh.Arguments.set_state({
        r'CFDSurfaceMeshControls': {r'DrawSizeControl': True,
                                    r'MaxSize': 819.2,
                                    r'MinSize': 10,
                                    r'SizeFunctions': r'Curvature',
        },
        r'ExecuteShareTopology': r'No',
        r'OriginalZones': [solid_face_zone],
        r'SeparationRequired': r'No',
        r'SurfaceMeshPreferences': {r'ShowSurfaceMeshPreferences': False,},
    })
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
    solid_region_name = solid_face_zone.removeprefix("origin-")
    update_regions.Arguments.set_state({
        r"OldRegionNameList": [r'fluid', solid_region_name],
        r"OldRegionTypeList": [r'fluid', r'fluid'],
        r"RegionNameList": [r'cone', r'farfield_volume'],
        r"RegionTypeList": [r'dead', r'fluid'],
    })
    update_regions.Execute()

    update_boundaries = watertight.update_boundaries # Load the Update Boundaries function
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

    # ---STEP 6: Generate Volume Mesh---
    farfield_volume_volume = meshy_session.scheme_eval.scheme_eval(
    f"(tgapi-util-get-region-volume '{solid_region_name}' farfield_volume )" # Get fluid volume in mm^3
    )

    cell_count = 0 # Initialize the cell count to 0
    target_cell_count = 750000 # Set the target cell count for the volume mesh
    hex_max_cell_length =  (farfield_volume_volume/target_cell_count)**(1/3) # Set the maximum cell length for the hexcore volume mesh
    volume_mesh = meshy_session.workflow.TaskObject["Generate the Volume Mesh"] # Load the Create Volume Mesh function
    volume_mesh.Arguments.set_state({
        r'MeshSolidRegions': False, # Only working with fluid regions
        r"VolumeFill": "poly-hexcore", #  Poly hexcore mesh type
        r'VolumeFillControls': {
            r'HexMaxCellLength': hex_max_cell_length, # Want hex cells to add up to atleast the target cell count. Basic calculation is used for estimate
            r'HexMaxSize': hex_max_cell_length,
            r'HexMinCellLength': 0.05,
        },
        r'VolumeMeshPreferences': {
            r'QualityWarningLimit': 0.15,
        },
    })

    volume_mesh.Execute()

    cell_count = meshy_session.meshing_utilities.get_cell_zone_count(
        cell_zone_name_pattern="*"
    )

    '''while(cell_count < 750000):
        hex_max_cell_length = hex_max_cell_length * (cell_count / target_cell_count)**(1/3) # Increase the maximum cell length by 10% if the cell count is not within the desired range

        volume_mesh.Arguments.set_state({
            r'MeshSolidRegions': False,
            r"VolumeFill": "poly-hexcore", 
            r'VolumeFillControls': {
                r'HexMaxCellLength': hex_max_cell_length,
                r'HexMaxSize': hex_max_cell_length,
                r'HexMinCellLength': 0.05,
            },
            r'VolumeMeshPreferences': {
                    r'QualityWarningLimit': 0.15,
            },
        })
        volume_mesh.Revert() # Revert the volume mesh to the previous state
        volume_mesh.Execute() # Re-execute the volume mesh function


        cell_count = meshy_session.meshing_utilities.get_cell_zone_count(
            cell_zone_name_pattern="*"
        )'''

    meshy_session.execute_tui(r'''/mesh/modify/improve-quality yes''')
    meshy_session.execute_tui(r'''/mesh/modify/auto-improve-warp yes''')

    print(f"---STEP 6: COMPLETED--- Created volume mesh for geometry: {import_file_name} into Fluent Meshing session.")

    # --STEP 7: Save and Export Mesh---
    meshy_session.tui.file.write_mesh(f"{msh_output_file_name}.msh.h5") # Save the mesh to a file
    print(f"---STEP 7: COMPLETED--- Saved and exported mesh for geometry: {import_file_name} into Fluent Meshing session.")

    # ---STEP 8: Switch to Solver Session and check mesh quality---
    solvy_session = meshy_session.switch_to_solver() # Switch to solver session
    solvy_session.settings.mesh.check() # Check the mesh quality
    print(f"---STEP 8: COMPLETED--- Switched to solver session and checked mesh quality for geometry: {import_file_name} into Fluent Meshing session.")


    # ---STEP 9: Define model, materials, and boundary conditions and other settings---
    viscous = solvy_session.setup.models.viscous # Load the Viscous Model function
    viscous.model = "k-omega" # Set the viscous model to k-omega
    viscous.k_omega_model = "sst" # Set the k-omega model to sst
    solvy_session.settings.setup.general.solver.type.set_state("density-based-implicit")

    air = solvy_session.settings.setup.materials.fluid["air"] # Load the air material properties
    air.density.option = "ideal-gas" # Set the density option for air to ideal gas
    air.viscosity.option = "sutherland" # Set the viscosity option for air to sutherland
    air.viscosity.sutherland.option = "three-coefficient-method" # Set the sutherland option for air to three coefficient method
    air.viscosity.sutherland.reference_viscosity = 1.716e-05 # Set the reference viscosity for air to 1.716e-05
    air.viscosity.sutherland.reference_temperature = 273.11 # Set the reference temperature for air to 273.11
    air.viscosity.sutherland.effective_temperature = 110.56 # Set the effective temperature for air to 110.56

    bc = solvy_session.settings.setup.boundary_conditions # Load the boundary conditions
    solvy_session.settings.setup.boundary_conditions.set_zone_type(
        zone_list=[solid_region_name + ':1'],
        new_type="pressure-far-field"
    )
    # print(bc.pressure_far_field.get_object_names()) # Get the object names for the pressure far field boundary condition
    farfield_names = bc.pressure_far_field.get_object_names() # Get the object names for the pressure far field boundary condition
    pressure_farfield = bc.pressure_far_field[farfield_names[0]] # Load the pressure far field boundary condition
    pressure_farfield.momentum.gauge_pressure = 0 # Set the gauge pressure for the pressure far field to 0
    pressure_farfield.momentum.mach_number = 2.0 # Set the mach number for the pressure far field to 2.0
    pressure_farfield.thermal.temperature = 288.15 # Set the temperature for the pressure far field to 288.15
    pressure_farfield.momentum.flow_direction[0] = 1.0 # Set the flow direction for the pressure far field to 1.0 in the x-direction
    pressure_farfield.turbulence.turbulent_intensity = 0.01
    pressure_farfield.turbulence.turbulent_viscosity_ratio = 10

    solvy_session.settings.setup.general.operating_conditions.operating_pressure = 80600
    solvy_session.settings.setup.general.operating_conditions.operating_pressure = 22632 

    solvy_session.execute_tui(r'''/solve/set/limits yes
    100
    5e+06
    50
    3000
    1e-14
    1e-14
    1e+5
    ''')

    D_mm = 2.8 * 304.8   # 2.8 ft in mm
    D_m = D_mm * 1.0e-3

    gamma = 1.4
    R_air = 287.05
    T_inf = 288.15
    p_inf = 22632.0
    M_inf = 2.0  # You set 2.0 in this script

    rho_inf = p_inf / (R_air * T_inf)
    a_inf = math.sqrt(gamma * R_air * T_inf)
    V_inf = M_inf * a_inf
    A_ref = math.pi * D_m**2 / 4.0

    ref = solvy_session.settings.setup.reference_values
    ref.area = A_ref
    ref.density = rho_inf
    ref.velocity = V_inf

    solvy_session.settings.solution.methods.spatial_discretization.discretization_scheme = {'k' : 'first-order-upwind', 'omega' : 'first-order-upwind', 'mom' : 'first-order-upwind'}
    solvy_session.execute_tui(r'''/solve/set/pseudo-time-method/relaxation-factors/omega 0.5''')
    solvy_session.execute_tui(r'''/solve/set/pseudo-time-method/relaxation-factors/k 0.5''')

    disc = solvy_session.settings.solution.methods.spatial_discretization.discretization_scheme
    print(disc.get_state())   # look at the actual keys Fluent reports
    disc.set_state({'flow': 'first-order-upwind', 'k': 'first-order-upwind', 'omega': 'first-order-upwind'})

   

    cone_wall_zone_name = cone_wall_zone.removeprefix("origin-").removesuffix(":8") + ':14'
    # solvy_session.settings.solution.report_definitions.drag["cd_monitor"] = {
         #"zones": [cone_wall_zone.removeprefix("origin-").removesuffix(":8") + ':14'],   # use your auto-detected cone wall zone           # flow direction
    # }

    '''solvy_session.settings.solution.initialization.hybrid_initialize()
    solvy_session.settings.solution.initialization.fmg.customize(multi_level_grid = 5, residual_reduction = [0.001, 0.001, 0.001, 0.001, 0.001], cycle_count = [100, 200, 400, 800, 800])
    solvy_session.settings.solution.initialization.fmg.fmg_initialize() # Initialize the solution using FMG'''

    init = solvy_session.settings.solution.initialization
    init.reference_frame = "absolute"
    init.compute_defaults.pressure_far_field[farfield_names[0]]()
    init.initialize()
    init.fmg.fmg_initialize()

    solvy_session.execute_tui(
        '''/solve/set/courant 0.5'''
    )

    solvy_session.execute_tui(r'''/solve/set/warped-face-gradient-correction/enable? yes''')

    solvy_session.execute_tui(r'''rpsetvar 'temperature/secondary-gradient? #f''')

    

    print(f"---STEP 9: COMPLETED--- Defined model, materials, and boundary conditions and other settings for geometry: {import_file_name} into Fluent Meshing session.")

    # ---STEP 10: Run the calculation and write results---

    iterations_per_block = 25
    number_of_blocks = 30

    reps = solvy_session.settings.solution.report_definitions # Load the report definitions
    reps.drag["cd_monitor"] = {
        "zones": [cone_wall_zone_name],   # use your auto-detected cone wall
    }

    cfl_schedule = [0.5, 1, 2, 5, 10]

    prev_cd = None
    for block in range(number_of_blocks):
        cfl = min(block, len(cfl_schedule) - 1)
        solvy_session.settings.solution.run_calculation.iterate(
            iter_count=iterations_per_block
        )
        solvy_session.execute_tui(
        f'''/solve/set/courant {cfl_schedule[cfl]}'''
        )

        cd = float(reps.drag["cd_monitor"].compute()[0])
        print(f"block {block}: Cd = {cd:.6f}")
        if prev_cd and abs(cd - prev_cd) / abs(cd) < 1e-4:
            break
        prev_cd = cd



    results = reps.compute(report_defs=["drag_force_x", "cd_x"])
    drag_N = float(results["drag_force_x"])
    Cd = float(results["cd_x"])

    current_iter = (block + 1) * iterations_per_block
    print(f"Iter {current_iter:4d} | Drag = {drag_N:.3f} N | Cd = {Cd:.6f}")
    
    # solvy_session.settings.solution.run_calculation.iterate(iter_count=3000) # Run the calculation for 3000 iterations
    # cd_value = solvy_session.settings.solution.report_definitions.compute(report_defs=["cd_monitor"])
    # print(cd_value)

    # ---STEP 11: Define reports, write to values to csv file, and write case and data files---

    cd_value = reps.drag["cd_monitor"].compute() # Compute the drag coefficient for the cone wall

    try:
        reps.drag["cd_pressure"] = {
            "zones": [cone_wall_zone_name],   # use your auto-detected cone wall
            "report_type": "force",
            "options": {"coeff": True, "type": "pressure"},
        }

        reps.drag["cd_viscous"] = {
            "zones": [cone_wall_zone_name],   # use your auto-detected cone wall
            "report_type": "max",              # facet-maximum
            "field": "pressure",              # static pressure
            "surfaces": [cone_wall_zone_name],
        }
    except:
        print("Error: Could not create cd_pressure and cd_viscous reports. Please check the zone names and report definitions.")

    with open(f'{cas_output_dir / "simulated.csv"}', mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([basename, cd_value]) # Write the drag coefficient value to the csv file




    solvy_session.settings.file.write(file_type="case", file_name=f"{cas_output_file_name}.cas.h5")
    solvy_session.settings.file.write(file_type="data", file_name=f"{cas_output_file_name}.dat.h5")

    solvy_session.exit()