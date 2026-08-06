import importlib
from pathlib import Path
import os
import sys

# Import CAD module
import gmsh

# Import file handling module
import glob

step_num = 0  # Initialize step number for tracking progress
counter = 1  # Initialize counter for tracking number of geometries processed

# Initialize gmsh and add the model
gmsh.initialize()
print(f"Initialized gmsh, beginning farfield processing...")

# Fix local pathing issues
SCRIPT_DIR = Path(__file__).resolve().parent
inp_geom_dir = Path(str(SCRIPT_DIR / "generated_geometries")) # Change to change outputs
opt_geom_dir = Path(str(SCRIPT_DIR / "farfield_optimized_geometries"))
opt_geom_dir.mkdir(exist_ok=True)

for input_path in glob.glob(os.path.join(inp_geom_dir, "*.stp")):
    step_num = 0  # Reset step number for each new geometry
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    print(f"Processing {base_name}...")
    gmsh.model.add(f"{base_name}_ffd")

    # Import the STEP file and its geometries and convert it to a list of shapes
    gmsh.model.occ.importShapes(str(inp_geom_dir / f"{base_name}.stp"))
    print(f"Imported STEP file and converted to shapes.[{(step_num := step_num + 1)}/3]")
    gmsh.model.occ.synchronize()
    print(f"Synchronized the CAD model with gmsh.[{(step_num := step_num + 1)}/3]")

    # Load volume entities from model
    volume = gmsh.model.occ.getEntities(dim=3)
    solid = volume[0]  # Assuming the first volume is the solid of interest

    # Find bounding box of the solid and compute characteristic lengths in x, y, and z directions
    x1, y1, z1, x2, y2, z2 = gmsh.model.occ.getBoundingBox(solid[0], solid[1])

    Lx = x2 - x1
    Ly = y2 - y1
    Lz = z2 - z1

    # print(f"Bounding box of the solid: x1={x1}, y1={y1}, z1={z1}, x2={x2}, y2={y2}, z2={z2}") # Testing bounding box values
    # print(f"Characteristic lengths: Lx={Lx}, Ly={Ly}, Lz={Lz}") # Testing characteristic lengths

    # print(nose_cone_geometry)

    # Initialize dimensions of farfield volume
    farfield_rear_length = 10.0*(Lx)
    farfield_front_length = 2.0*(Lx)
    farfield_diameter = 3.0*(Ly)
    farfield_total_length = farfield_rear_length + Lx + farfield_front_length

    # Initialize volume location
    farfield_x_pos = x1 - farfield_front_length
    farfield_y_pos = 0.0
    farfield_z_pos = 0.0

    # Build the cylinder representing the farfield volume
    farfield_tag = gmsh.model.occ.addCylinder(farfield_x_pos, farfield_y_pos, farfield_z_pos, farfield_total_length, 0.0, 0.0, farfield_diameter/2.0)
    gmsh.model.occ.synchronize()
    print(f"Created farfield volume with tag {farfield_tag}. [{(step_num := step_num + 1)}/3]")

    # Cut the farfield volume with the solid to create the final geometry
    fluid_tag = gmsh.model.occ.cut([(3, farfield_tag)], [(3, solid)], removeObject=True, removeTool=True)
    gmsh.model.occ.synchronize()
    print(f"Cut the farfield volume with the solid. Resulting fluid domain tag: {fluid_tag}.")

    gmsh.option.setNumber("Geometry.OCCBoundsUseStl", 1)
    gmsh.model.occ.removeAllDuplicates()

    # Cut half of the farfield volume to create a half-domain for symmetry and reduced computational cost
    # remove_half_tag = gmsh.model.occ.addBox(farfield_x_pos-10.0, 0.0, 0.0, farfield_total_length+20.0, farfield_diameter, farfield_diameter)

    # Write the final geometry to a STEP file
    gmsh.write(str(opt_geom_dir / f"{base_name}_ffd.stp"))

    # Display file in window
    # if 'close' not in sys.argv:
        # gmsh.fltk.run()

    print(gmsh.model.getEntities(dim=3))

    # (For looping only) clear the model to prepare for the next iteration
    gmsh.model.remove()

    print(f"Finished processing {base_name}.[{(counter := counter + 1)}/{len(glob.glob(os.path.join(inp_geom_dir, '*.stp')))}]")

# Finalize gmsh
gmsh.finalize()


