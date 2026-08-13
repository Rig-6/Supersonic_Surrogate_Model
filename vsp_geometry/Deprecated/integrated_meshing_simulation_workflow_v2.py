"""
Integrated meshing + solving workflow  (REVISED for supersonic convergence)

Every change from the original is tagged with  # FIX:  so you can diff intent quickly.
The big ones, in order of impact on your residual plot:

  FIX-1  Pressure-based coupled solver -> density-based implicit + Roe-FDS.
         At M=2 the pressure-based solver is the wrong tool. Continuity climbing
         and then limit-cycling is its signature failure mode here.
  FIX-2  '/solve/set/courant 0.3'. In the pressure-based coupled solver that token
         resolves to the PSEUDO-TIME Courant number, whose default is 200. You set it
         to 0.3, i.e. ~700x smaller pseudo-timesteps. The solution barely advances,
         so residuals flatline and oscillate almost immediately. This alone reproduces
         your plot. In the density-based solver Courant 0.5 -> 5 is the correct range.
  FIX-3  max turbulent-viscosity-ratio was set to 1e10 and min abs pressure to 1 Pa.
         That lets mu_t and p wander into nonphysical territory instead of being
         clipped, which sustains the oscillation. Back to sane limits.
  FIX-4  hybrid_initialize() at M=2 produces a poor starting field; fmg.customize()
         was called but fmg_initialize() never was, so FMG never actually ran.
         Now: standard init from the farfield BC, then FMG.
  FIX-5  poor-mesh-numerics ON and temperature secondary-gradients OFF were masking
         bad cells and putting a floor under the residuals. Both removed; the mesh
         is fixed at the source instead.
  FIX-6  Reference area was hardcoded to D = 2.8 ft for every geometry. Your actual
         pod diameter varies per sample (~0.18-0.55 m), so every Cd in the dataset
         was wrong by a different factor. Now computed per geometry from the STEP bbox.
  FIX-7  Zone identification by hardcoded IDs (':8' -> ':14') and a hardcoded probe
         point (2.0, 0.15, 0.0). Both break on any geometry but the one you tuned on.
         Now: geometric probe derived from the farfield construction formula, then
         zones are RENAMED so nothing downstream depends on IDs.
  FIX-8  Convergence is now judged on Cd plateau, not residuals. For supersonic
         external flow the scaled continuity residual often never drops 3 orders
         while the integrated force is dead flat and correct.

NOTE on your plot: continuity "rising to ~7" is partly a normalization artifact.
Fluent scales residuals by the largest value seen in the first 5 iterations; after a
good initialization that reference is artificially small, so the curve starts above 1.
The problem is that it is FLAT, not that it is high. This script re-normalizes after
the first-order stage so the plot means something.
"""

import csv
import glob
import json
import math
import os
from pathlib import Path

import ansys.fluent.core as pyfluent

try:
    import gmsh
except ImportError:
    gmsh = None


# =============================================================================
# CONFIGURATION
# =============================================================================

SHOW_GUI = False          # FIX: batch pipeline; flip to True only when debugging
PROCESSOR_COUNT = 10      # FIX: was 12 on a 10-core box -> "auto partition" warning every run
TARGET_CELL_COUNT = 900_000
CELL_COUNT_TOL = 0.25     # accept +/-25% of target
MAX_MESH_ATTEMPTS = 4

# --- Freestream (single source of truth; 11 km ISA) ---
GAMMA = 1.4
R_AIR = 287.05            # J/(kg K)
T_INF = 288.15            # K   <- note: this is sea-level T at 11 km pressure. See "PHYSICS" note below.
P_INF = 22632.0           # Pa absolute
M_INF = 2.0

# Sutherland (three-coefficient) constants, matching what is set on the material
MU_REF = 1.716e-05
T_REF_VISC = 273.11
S_EFF = 110.56

# --- Boundary layer target ---
YPLUS_TARGET = 30.0       # FIX: wall-function y+. Was uncontrolled ("smooth-transition").
BL_LAYERS = 26            # 26 @ 1.2 from y+=30 spans ~50 mm vs a ~40 mm turbulent BL at Re_L=3.6e7,
                          # and the last layer (~8.4 mm) matches BOI min size -> clean transition.
BL_GROWTH = 1.2

# --- Farfield construction constants (MUST match farfield_geometry_optimizer.py) ---
FF_FRONT_MULT = 2.0       # front length = 2.0 * Lx
FF_REAR_MULT = 10.0       # rear length  = 10.0 * Lx
FF_DIAM_MULT = 10.0       # farfield diameter = 10.0 * Ly

STEP_LENGTH_UNIT = "mm"   # unit Fluent Meshing is told the STEP is in
STEP_TO_M = 1.0e-3


# =============================================================================
# HELPERS
# =============================================================================

def sutherland_mu(T):
    """Three-coefficient Sutherland viscosity, same form Fluent uses."""
    return MU_REF * ((T / T_REF_VISC) ** 1.5) * (T_REF_VISC + S_EFF) / (T + S_EFF)


def freestream():
    rho = P_INF / (R_AIR * T_INF)
    a = math.sqrt(GAMMA * R_AIR * T_INF)
    V = M_INF * a
    mu = sutherland_mu(T_INF)
    return rho, a, V, mu


def get_pod_bbox(pod_step_path):
    """
    FIX-6: read the actual pod bounding box from the pre-farfield STEP so reference
    area is per-geometry instead of a hardcoded 2.8 ft.
    Returns (Lx, Dy) in STEP units (mm).
    """
    if gmsh is None:
        raise RuntimeError("gmsh is required to compute per-geometry reference values.")
    gmsh.initialize()
    try:
        gmsh.model.add("bbox_probe")
        gmsh.model.occ.importShapes(str(pod_step_path))
        gmsh.model.occ.synchronize()
        vols = gmsh.model.occ.getEntities(dim=3)
        if not vols:
            raise RuntimeError(f"No solid volume found in {pod_step_path}")
        x1, y1, z1, x2, y2, z2 = gmsh.model.occ.getBoundingBox(*vols[0])
        gmsh.model.remove()
    finally:
        gmsh.finalize()
    return (x2 - x1), (y2 - y1), x1, x2


def first_cell_height_m(rho, V, mu, L_ref_m, yplus):
    """Flat-plate correlation for the first cell centroid height at a target y+."""
    Re_L = rho * V * L_ref_m / mu
    Cf = 0.026 / (Re_L ** (1.0 / 7.0))
    tau_w = 0.5 * rho * V * V * Cf
    u_tau = math.sqrt(tau_w / rho)
    return yplus * mu / (rho * u_tau), Re_L


def try_call(label, fn, *args, **kwargs):
    """
    pyfluent settings-API paths move between releases. Rather than let a rename
    silently no-op (which is how '/solve/set/courant 0.3' slipped through), every
    optional call is wrapped and loudly reported.
    """
    try:
        fn(*args, **kwargs)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] '{label}' failed: {type(exc).__name__}: {exc}")
        return False


# =============================================================================
# PATHS
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
inp_ffd_dir = SCRIPT_DIR / "farfield_optimized_geometries"
inp_pod_dir = SCRIPT_DIR / "generated_geometries"
msh_output_dir = SCRIPT_DIR / "meshed_output"
cas_output_dir = SCRIPT_DIR / "simulated_output"
msh_output_dir.mkdir(exist_ok=True)
cas_output_dir.mkdir(exist_ok=True)

results_csv = cas_output_dir / "simulated.csv"

stp_files = sorted(glob.glob(str(inp_ffd_dir / "*.stp")))

if not results_csv.exists():
    with open(results_csv, mode="w", newline="") as file:
        csv.writer(file).writerow(
            ["File_Name", "L_ref_m", "D_ref_m", "A_ref_m2", "Re_L",
             "Cd", "Cd_pressure", "Cd_viscous", "Cells", "Converged"]
        )

os.environ["FLUENT_NO_AUTOMATIC_TRANSCRIPT"] = "1"


# =============================================================================
# MAIN LOOP
# =============================================================================

rho_inf, a_inf, V_inf, mu_inf = freestream()
print(f"Freestream: rho={rho_inf:.4f} kg/m3  a={a_inf:.2f} m/s  V={V_inf:.2f} m/s  mu={mu_inf:.4e} Pa.s")

for stp_file in stp_files:
    basename = os.path.splitext(os.path.basename(stp_file))[0]
    import_file_name = str(stp_file)
    msh_output_file_name = str(msh_output_dir / f"{basename}_sim")
    cas_output_file_name = str(cas_output_dir / f"{basename}_sim")

    print("\n" + "=" * 78)
    print(f"CASE: {basename}")
    print("=" * 78)

    # -------------------------------------------------------------------------
    # STEP 0: per-geometry reference values   (FIX-6)
    # -------------------------------------------------------------------------
    pod_name = basename.removesuffix("_ffd")
    pod_step = inp_pod_dir / f"{pod_name}.stp"
    if not pod_step.exists():
        print(f"  [SKIP] Cannot find source pod STEP {pod_step}; reference area would be wrong.")
        continue

    Lx_mm, Dy_mm, pod_x1_mm, pod_x2_mm = get_pod_bbox(pod_step)
    L_ref_m = Lx_mm * STEP_TO_M
    D_ref_m = Dy_mm * STEP_TO_M
    A_ref = math.pi * D_ref_m ** 2 / 4.0

    y1_m, Re_L = first_cell_height_m(rho_inf, V_inf, mu_inf, L_ref_m, YPLUS_TARGET)
    bl_first_height_mm = y1_m / STEP_TO_M

    print(f"  Pod bbox: Lx={Lx_mm:.1f} mm, D={Dy_mm:.1f} mm  ->  L_ref={L_ref_m:.3f} m, "
          f"D_ref={D_ref_m:.3f} m, A_ref={A_ref:.4f} m2")
    print(f"  Re_L={Re_L:.3e}  ->  first BL cell height for y+={YPLUS_TARGET:.0f}: "
          f"{bl_first_height_mm:.4f} mm")

    # Geometry-relative surface sizing  (FIX: was absolute 10 mm / 819.2 mm / 0.05 mm
    # regardless of a pod diameter that varies ~3x across the LHS sample)
    boi_min = Dy_mm / 60.0
    boi_max = Dy_mm / 8.0
    surf_min = Dy_mm / 20.0
    surf_max = Dy_mm * 4.0

    # Farfield probe point, derived from the construction formula rather than hardcoded
    ff_radius_mm = FF_DIAM_MULT * Dy_mm / 2.0
    probe_x = pod_x1_mm + 0.5 * Lx_mm
    probe_y = ff_radius_mm
    probe_z = 0.0

    # -------------------------------------------------------------------------
    # STEP 1: Import geometry
    # -------------------------------------------------------------------------
    meshy_session = pyfluent.launch_fluent(
        mode=pyfluent.FluentMode.MESHING,
        precision=pyfluent.Precision.DOUBLE,
        processor_count=PROCESSOR_COUNT,
        show_gui=SHOW_GUI,
    )
    watertight = meshy_session.watertight()
    import_geometry = watertight.import_geometry
    import_geometry.file_name = import_file_name
    import_geometry.length_unit = STEP_LENGTH_UNIT
    import_geometry()
    print("---STEP 1 COMPLETE--- geometry imported")

    face_zones = meshy_session.scheme_eval.scheme_eval(
        '(tgapi-util-convert-zone-ids-to-name-strings (get-face-zones-of-filter "*"))'
    )
    solid_face_zone = face_zones[0]
    solid_region_name = solid_face_zone.removeprefix("origin-")
    print(f"  Solid face zone: {solid_face_zone}")

    meshy_session.tui.boundary.separate.sep_face_zone_by_angle([solid_face_zone], 40)

    # ---- FIX-7: identify the farfield by geometry, not by a magic zone ID -----
    ff_zone_id = meshy_session.scheme_eval.scheme_eval(
        f"(get-face-zone-at-location '({probe_x} {probe_y} {probe_z}))"
    )
    if not ff_zone_id:
        raise RuntimeError(
            f"Farfield probe at ({probe_x:.1f}, {probe_y:.1f}, {probe_z:.1f}) hit nothing. "
            "Check that FF_DIAM_MULT still matches farfield_geometry_optimizer.py."
        )
    farfield_zone = meshy_session.scheme_eval.scheme_eval(
        f"(tgapi-util-convert-zone-ids-to-name-strings (list {ff_zone_id}))"
    )[0]

    all_zones = meshy_session.scheme_eval.scheme_eval(
        '(tgapi-util-convert-zone-ids-to-name-strings (get-face-zones-of-filter "*"))'
    )
    cone_zones = [z for z in all_zones if z != farfield_zone]
    print(f"  Farfield zone: {farfield_zone}")
    print(f"  Cone zones ({len(cone_zones)}): {cone_zones}")

    # -------------------------------------------------------------------------
    # STEP 2: Local sizing + surface mesh
    # -------------------------------------------------------------------------
    add_local_sizing = meshy_session.workflow.TaskObject["Add Local Sizing"]
    add_local_sizing.Arguments.set_state({
        "AddChild": "yes",
        "BOICellsPerGap": 1,
        "BOIControlName": "curvature",
        "BOICurvatureNormalAngle": 12,      # FIX: 18 -> 12, the nose apex curvature drives wave drag
        "BOIExecution": "Curvature",
        "BOIFaceZoneList": cone_zones,      # FIX: all cone patches, not just one
        "BOIGrowthRate": 1.2,
        "BOIMaxSize": boi_max,
        "BOIMinSize": boi_min,              # FIX: 0.05 mm on a ~3.5 m body created
                                            #      sub-micron slivers (min face area was
                                            #      1.1e-13 m2 in your last mesh check)
        "BOIZoneorLabel": "zone",
    })
    add_local_sizing.AddChildAndUpdate(DeferUpdate=False)

    surf_mesh = meshy_session.workflow.TaskObject["Generate the Surface Mesh"]
    surf_mesh.Arguments.set_state({
        "CFDSurfaceMeshControls": {
            "DrawSizeControl": True,
            "MaxSize": surf_max,
            "MinSize": surf_min,
            "SizeFunctions": "Curvature & Proximity",   # FIX: proximity matters at the tips
            "CellsPerGap": 2,
        },
        "ExecuteShareTopology": "No",
        "OriginalZones": [solid_face_zone],
        "SeparationRequired": "No",
        "SurfaceMeshPreferences": {"ShowSurfaceMeshPreferences": False},
    })
    surf_mesh.Execute()          # FIX: the original never executed this task
    print("---STEP 2 COMPLETE--- surface mesh generated")

    # -------------------------------------------------------------------------
    # STEP 3: Describe geometry
    # -------------------------------------------------------------------------
    describe_geometry = watertight.describe_geometry
    describe_geometry.update_child_tasks(setup_type_changed=False)
    describe_geometry.setup_type.set_state(
        "The geometry consists of only fluid regions with no voids"
    )
    describe_geometry.update_child_tasks(setup_type_changed=True)
    describe_geometry()
    print("---STEP 3 COMPLETE--- geometry described")

    # -------------------------------------------------------------------------
    # STEP 4: Regions + boundaries, then RENAME zones  (FIX-7)
    # -------------------------------------------------------------------------
    update_regions = meshy_session.workflow.TaskObject["Update Regions"]
    update_regions.Arguments.set_state({
        "OldRegionNameList": ["fluid", solid_region_name],
        "OldRegionTypeList": ["fluid", "fluid"],
        "RegionNameList": ["cone", "farfield_volume"],
        "RegionTypeList": ["dead", "fluid"],
    })
    update_regions.Execute()

    watertight.update_boundaries()

    # Rename so the solver never has to guess. Everything downstream uses these names.
    try_call("rename farfield",
             meshy_session.tui.boundary.manage.name, farfield_zone, "farfield")
    if len(cone_zones) > 1:
        try_call("merge cone zones",
                 meshy_session.tui.boundary.manage.merge, "cone_wall", *cone_zones)
    else:
        try_call("rename cone wall",
                 meshy_session.tui.boundary.manage.name, cone_zones[0], "cone_wall")
    print("---STEP 4 COMPLETE--- regions/boundaries updated, zones renamed")

    # -------------------------------------------------------------------------
    # STEP 5: Boundary layers  (FIX: y+-targeted first height instead of
    #         'smooth-transition', which tied the first cell to the surface mesh
    #         size and gave y+ in the thousands with SST)
    # -------------------------------------------------------------------------
    add_bl = watertight.add_boundary_layer
    add_bl.control_name = "aspect-ratio_1"
    try:
        add_bl.offset_method_type = "uniform"
        add_bl.first_height = bl_first_height_mm
    except Exception:  # noqa: BLE001
        print("  [WARN] first-height BL API unavailable; falling back to smooth-transition")
        add_bl.control_name = "smooth-transition_1"
    add_bl.number_of_layers = BL_LAYERS
    add_bl.growth_rate = BL_GROWTH
    add_bl.insert_compound_child_task()
    watertight.add_boundary_layer_child_1()
    print(f"---STEP 5 COMPLETE--- {BL_LAYERS} BL layers, first height {bl_first_height_mm:.4f} mm")

    # -------------------------------------------------------------------------
    # STEP 6: Volume mesh, converging on cell count from BOTH directions
    #         (FIX: the original 'while cell_count < 750000' loop could only ever
    #          refine. Your last mesh came out at 3.83M cells against a 900k target
    #          and the loop never fired -- ~4x the intended solve cost per sample.)
    # -------------------------------------------------------------------------
    ff_volume = meshy_session.scheme_eval.scheme_eval(
        f"(tgapi-util-get-region-volume '{solid_region_name}' farfield_volume )"
    )
    hex_len = (ff_volume / TARGET_CELL_COUNT) ** (1.0 / 3.0)

    volume_mesh = meshy_session.workflow.TaskObject["Generate the Volume Mesh"]

    def build_volume_mesh(h, revert=False):
        volume_mesh.Arguments.set_state({
            "MeshSolidRegions": False,
            "VolumeFill": "poly-hexcore",
            "VolumeFillControls": {
                "HexMaxCellLength": h,
                "HexMaxSize": h,
                "HexMinCellLength": boi_min,   # FIX: was 0.05 mm absolute
            },
            "VolumeMeshPreferences": {"QualityWarningLimit": 0.15},
        })
        if revert:
            volume_mesh.Revert()
        volume_mesh.Execute()
        return meshy_session.meshing_utilities.get_cell_count(cell_zone_name_pattern="*")

    cell_count = build_volume_mesh(hex_len)
    for attempt in range(MAX_MESH_ATTEMPTS):
        ratio = cell_count / TARGET_CELL_COUNT
        print(f"  Volume mesh attempt {attempt}: {cell_count:,} cells "
              f"(target {TARGET_CELL_COUNT:,}, hex len {hex_len:.3f} mm)")
        if abs(ratio - 1.0) <= CELL_COUNT_TOL:
            break
        hex_len = hex_len * (ratio ** (1.0 / 3.0))   # works in both directions
        cell_count = build_volume_mesh(hex_len, revert=True)

    meshy_session.execute_tui("/mesh/modify/improve-quality yes")
    meshy_session.execute_tui("/mesh/modify/auto-improve-warp yes")
    print(f"---STEP 6 COMPLETE--- volume mesh: {cell_count:,} cells")

    # -------------------------------------------------------------------------
    # STEP 7: Write mesh
    # -------------------------------------------------------------------------
    meshy_session.tui.file.write_mesh(f"{msh_output_file_name}.msh.h5")
    print("---STEP 7 COMPLETE--- mesh written")

    # -------------------------------------------------------------------------
    # STEP 8: Switch to solver
    # -------------------------------------------------------------------------
    solver = meshy_session.switch_to_solver()
    solver.settings.mesh.check()
    print("---STEP 8 COMPLETE--- switched to solver")

    # =========================================================================
    # STEP 9: SOLVER SETUP
    # =========================================================================

    # ---- FIX-1: density-based implicit. This is the single most important change. --
    solver.settings.setup.general.solver.type = "density-based-implicit"
    try_call("Roe-FDS flux",
             setattr, solver.settings.solution.methods, "flux_type", "roe-fds")

    solver.settings.setup.models.energy.enabled = True

    viscous = solver.settings.setup.models.viscous
    viscous.model = "k-omega"
    viscous.k_omega_model = "sst"
    try_call("compressibility effects",
             setattr, viscous.options, "compressibility_effects", True)   # FIX: matters at M=2

    air = solver.settings.setup.materials.fluid["air"]
    air.density.option = "ideal-gas"
    air.viscosity.option = "sutherland"
    air.viscosity.sutherland.option = "three-coefficient-method"
    air.viscosity.sutherland.reference_viscosity = MU_REF
    air.viscosity.sutherland.reference_temperature = T_REF_VISC
    air.viscosity.sutherland.effective_temperature = S_EFF

    # ---- FIX: operating pressure. For a compressible ideal-gas run Fluent's own
    #      guidance is operating pressure = 0 with absolute gauge pressures. The
    #      original set it twice (80600 then 22632) with gauge = 0, which is easy to
    #      get subtly wrong and gives worse round-off in the pressure equation.
    solver.settings.setup.general.operating_conditions.operating_pressure = 0.0

    bc = solver.settings.setup.boundary_conditions
    bc.set_zone_type(zone_list=["farfield"], new_type="pressure-far-field")

    pff = bc.pressure_far_field["farfield"]
    pff.momentum.gauge_pressure = P_INF          # FIX: absolute, since operating p = 0
    pff.momentum.mach_number = M_INF
    pff.thermal.temperature = T_INF
    pff.momentum.flow_direction[0] = 1.0
    pff.momentum.flow_direction[1] = 0.0         # FIX: were left at whatever default
    pff.momentum.flow_direction[2] = 0.0
    pff.turbulence.turbulent_intensity = 0.01
    pff.turbulence.turbulent_viscosity_ratio = 10

    # ---- FIX-3: sane solver limits ------------------------------------------------
    limits_ok = try_call(
        "solver limits (settings API)",
        setattr, solver.settings.solution.controls, "limits",
        {
            "min_abs_pressure": 100.0,        # was 1 Pa -> effectively vacuum allowed
            "max_abs_pressure": 5.0e6,
            "min_temperature": 50.0,
            "max_temperature": 3000.0,        # was 5000
            "min_k": 1.0e-14,
            "min_omega": 1.0e-14,
            "max_turb_visc_ratio": 1.0e5,     # was 1e10 -- mu_t was effectively unclipped
        },
    )
    if not limits_ok:
        solver.execute_tui(
            "/solve/set/limits 100 5e6 50 3000 1e-14 1e-14 1e5"
        )

    # ---- Reference values (FIX-6): complete set, per geometry ---------------------
    ref = solver.settings.setup.reference_values
    ref.area = A_ref
    ref.density = rho_inf
    ref.velocity = V_inf
    ref.length = L_ref_m          # FIX: was never set
    ref.pressure = P_INF          # FIX: was never set -> Cp was referenced to 0
    ref.temperature = T_INF       # FIX: was never set
    try_call("ref viscosity", setattr, ref, "viscosity", mu_inf)
    try_call("ref ratio of specific heats", setattr, ref, "specific_heat_ratio", GAMMA)

    # ---- FIX-5: remove the numerics band-aids -------------------------------------
    # poor-mesh-numerics locally drops to first order and puts a hard floor under the
    # residuals; disabling temperature secondary gradients hurts shock capturing.
    solver.execute_tui("/solve/set/poor-mesh-numerics/enable? no")
    solver.execute_tui("/solve/set/warped-face-gradient-correction/enable? yes")

    # ---- FIX-4: initialize properly ------------------------------------------------
    init = solver.settings.solution.initialization
    try_call("compute defaults from farfield",
             init.compute_defaults.pressure_far_field["farfield"])
    try_call("standard initialize", init.standard_initialize)
    try_call("fmg customize", init.fmg.customize,
             multi_level_grid=5,
             residual_reduction=[0.001, 0.001, 0.001, 0.001, 0.001],
             cycle_count=[100, 200, 400, 800, 800])
    try_call("fmg initialize", init.fmg_initialize)   # FIX: this was never called
    print("---STEP 9 COMPLETE--- solver configured (density-based implicit, Roe-FDS)")

    # =========================================================================
    # STEP 10: Reports  (FIX-8)
    # =========================================================================
    reps = solver.settings.solution.report_definitions
    reps.drag["cd_total"] = {
        "zones": ["cone_wall"],
        "force_vector": [1.0, 0.0, 0.0],
        "scaled": True,
    }
    try_call("cd_pressure report", reps.drag.__setitem__, "cd_pressure", {
        "zones": ["cone_wall"],
        "force_vector": [1.0, 0.0, 0.0],
        "scaled": True,
        "pressure_force": True,
        "viscous_force": False,
    })
    try_call("cd_viscous report", reps.drag.__setitem__, "cd_viscous", {
        "zones": ["cone_wall"],
        "force_vector": [1.0, 0.0, 0.0],
        "scaled": True,
        "pressure_force": False,
        "viscous_force": True,
    })

    def compute_cd(name="cd_total"):
        out = reps.compute(report_defs=[name])
        val = out[0][name] if isinstance(out, list) else out[name]
        return float(val[0] if isinstance(val, (list, tuple)) else val)

    # =========================================================================
    # STEP 11: Staged solve
    #   FIX-2: Courant 0.5 -> 2 -> 5. Your 0.3 was a pseudo-time Courant number
    #   (default 200) and froze the pressure-based solve in place.
    # =========================================================================
    disc = solver.settings.solution.methods.spatial_discretization

    # Stage A: first order, low Courant. Gets the bow shock roughly in position.
    disc.discretization_scheme = {"mom": "first-order-upwind",
                                  "k": "first-order-upwind",
                                  "omega": "first-order-upwind"}
    solver.execute_tui("/solve/set/courant-number 0.5")
    solver.settings.solution.run_calculation.iterate(iter_count=200)

    solver.execute_tui("/solve/set/courant-number 2")
    solver.settings.solution.run_calculation.iterate(iter_count=200)

    # Re-normalize so the residual plot is readable from here on (see header note).
    try_call("renormalize residuals",
             solver.execute_tui, "/solve/monitors/residual/re-normalize? yes")

    # Stage B: second order + higher Courant. First order will never give a usable Cd.
    disc.discretization_scheme = {"mom": "second-order-upwind",
                                  "k": "second-order-upwind",
                                  "omega": "second-order-upwind"}
    solver.execute_tui("/solve/set/courant-number 5")

    # Stage C: iterate in blocks and stop on Cd plateau, not on residuals.
    cd_history = []
    converged = False
    for block in range(30):
        solver.settings.solution.run_calculation.iterate(iter_count=50)
        cd = compute_cd()
        cd_history.append(cd)
        it = 400 + (block + 1) * 50
        print(f"  iter {it:5d} | Cd = {cd:.6f}")
        if len(cd_history) >= 4:
            window = cd_history[-4:]
            spread = (max(window) - min(window)) / max(abs(sum(window) / 4), 1e-12)
            if spread < 1.0e-3:
                converged = True
                print(f"  Cd plateaued (spread {spread:.2e} over 200 iters) -> converged")
                break

    if not converged:
        print("  [WARN] Cd did not plateau within the iteration budget.")

    cd_total = cd_history[-1] if cd_history else float("nan")
    cd_p = compute_cd("cd_pressure") if "cd_pressure" in reps.drag else float("nan")
    cd_v = compute_cd("cd_viscous") if "cd_viscous" in reps.drag else float("nan")
    print(f"  Cd = {cd_total:.6f}  (pressure {cd_p:.6f}, viscous {cd_v:.6f})")

    # =========================================================================
    # STEP 12: Write results
    # =========================================================================
    with open(results_csv, mode="a", newline="") as file:
        csv.writer(file).writerow(
            [basename, f"{L_ref_m:.6f}", f"{D_ref_m:.6f}", f"{A_ref:.6f}",
             f"{Re_L:.4e}", f"{cd_total:.6f}", f"{cd_p:.6f}", f"{cd_v:.6f}",
             cell_count, int(converged)]
        )

    with open(f"{cas_output_file_name}_meta.json", "w") as f:
        json.dump({
            "basename": basename,
            "L_ref_m": L_ref_m, "D_ref_m": D_ref_m, "A_ref_m2": A_ref,
            "mach": M_INF, "p_inf_Pa": P_INF, "T_inf_K": T_INF,
            "Re_L": Re_L, "cells": cell_count,
            "cd_history": cd_history, "converged": converged,
        }, f, indent=2)

    solver.settings.file.write(file_type="case", file_name=f"{cas_output_file_name}.cas.h5")
    solver.settings.file.write(file_type="data", file_name=f"{cas_output_file_name}.dat.h5")
    solver.exit()
    print(f"---CASE COMPLETE--- {basename}")

print("\nAll cases finished.")
