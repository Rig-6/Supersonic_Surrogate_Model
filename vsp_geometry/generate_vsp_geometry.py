# Allow python to find modules located elsewhere within the operating system
import sys
import os

# Data formatting through the csv module
import csv

# The numpy module for mathematical operations
import numpy as np

# The vsp module for generating the geometries
import vsp

# --> Section 1: Generate parameter limit lists

lengths = np.linspace(5, 15.0, 3)
diameters = np.linspace(1.0, 3.0, 3)
nose_radii = np.linspace(.1, 0.5, 3)

iteration_total = len(lengths) * len(diameters) * len(nose_radii)

print(f"Generating {iteration_total} nose cones with parameter combinations")

# --> Section 2: Create the CSV file to store the parameter combinations

with open('parameter_combinations.csv', mode='w', newline='') as csv_file:
    writer = csv.writer(csv_file)
    writer.writerow(['Length', 'Diameter', 'Nose_Radius', 'Fineness_Ratio', 'STL_File_Name'])

# --> Section 3: Generate the geometries and save them as STL files

for L in lengths:
    for D in diameters:
        for R in nose_radii:
            
            # Clean OpenVSP Workspace
            vsp.ClearVSPModel()

            # Create geometry
            nose_cone_id = vsp.AddGeom("POD")
            fineness = L/D

            # Modify geometry parameters
            vsp.SetParmVal(nose_cone_id, "Length", "Design", L)
            vsp.SetParmVal(nose_cone_id, "Fineness", "Design", fineness)

            vsp.SetParmVal(nose_cone_id, "Nose_Radius", "Design", R)
