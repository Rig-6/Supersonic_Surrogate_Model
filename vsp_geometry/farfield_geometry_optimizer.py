import importlib
from pathlib import Path
import os
import sys

# Import CAD module
import gmsh

step_num = 0  # Initialize step number for tracking progress

# Initialize gmsh and add the model
gmsh.initialize()
gmsh.model.add("farfield_volume_geometry")
print(f"Initialized gmsh and added model for farfield volume geometry.[{step_num+1}]")

# Fix local pathing issues
SCRIPT_DIR = Path(__file__).resolve().parent
opt_geom_dir = Path(SCRIPT_DIR / "generated_geometries" / "optimized_geometries")
opt_geom_dir.mkdir(exist_ok=True)


# Import the STEP file and its geometries and convert it to a list of shapes
gmsh.model.occ.importShapes(str(SCRIPT_DIR / "generated_geometries" / "cone_L50.0_D5.0_R1.0.stp"))
step_num += 1
print(f"Imported STEP file and converted to shapes.[{step_num+1}]")

step_num += 1
print(f"Synchronized the CAD model with gmsh.[{step_num+1}]")

# Load volume entities from model
volume = gmsh.model.occ.getEntities(dim=3)
solid = volume[0]  # Assuming the first volume is the solid of interest

# Find bounding box of the solid and compute characteristic lengths in x, y, and z directions
x1, y1, z1, x2, y2, z2 = gmsh.model.occ.getBoundingBox(solid[0], solid[1])

Lx = x2 - x1
Ly = y2 - y1
Lz = z2 - z1

print(f"Bounding box of the solid: x1={x1}, y1={y1}, z1={z1}, x2={x2}, y2={y2}, z2={z2}")
print(f"Characteristic lengths: Lx={Lx}, Ly={Ly}, Lz={Lz}")



step_num += 1
print(f"Computed characteristic lengths.[{step_num+1}]")

# print(nose_cone_geometry)
print(f"Imported STEP file and converted to shapes.[{step_num+1}]")


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
print(f"Created farfield volume with tag {farfield_tag}.")

# Cut the farfield volume with the solid to create the final geometry
fluid_tag = gmsh.model.occ.cut([(3, farfield_tag)], [(solid)], removeObject=True)
gmsh.model.occ.synchronize()
print(f"Cut the farfield volume with the solid. Resulting fluid domain tag: {fluid_tag}.")

# Write the final geometry to a STEP file
gmsh.write(str(opt_geom_dir / "farfield_volume_geometry.step"))

# Display file in window
if 'close' not in sys.argv:
    gmsh.fltk.run()

# Finalize gmsh
gmsh.finalize()


