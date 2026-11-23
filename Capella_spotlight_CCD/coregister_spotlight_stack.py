#!/usr/bin/env python
"""Coregister Capella spotlight SLCs onto one master. Run from capella-reader/docs/examples/.

python coregister_stack.py MASTER.tif SEC1.tif SEC2.tif ... [--dem-file DEM.tif] [--output-dir stack]
"""
import argparse, shutil, time, traceback
from pathlib import Path

from coreg_utils import create_dem, run_geometry
from coregister_isce3 import compute_fine_offsets, resample_slc, run_geo2rdr
from coregister_spotlight import combine_offsets
from restore_spotlight_phase import apply_spotlight_phase_restoration

p = argparse.ArgumentParser()
p.add_argument('master', type=Path)
p.add_argument('secondaries', type=Path, nargs='+')
p.add_argument('--dem-file', type=Path, default=None)
p.add_argument('--output-dir', type=Path, default=Path('stack'))
a = p.parse_args()

out = a.output_dir; out.mkdir(parents=True, exist_ok=True)
# the master may be in the list (e.g. from a glob): skip it. Sorted = chronological for Capella names
secs = sorted(s for s in a.secondaries if s.resolve() != a.master.resolve())
mdate = a.master.stem.split('_')[5][:8]       # CAPELLA_C13_SP_SLC_HH_<start>_<end>

with open(out / 'stack.txt', 'w') as f:       # slvN <-> file mapping (keep the list unchanged between runs)
    f.write(f'mst\t{a.master.name}\n')
    for i, s in enumerate(secs, 1): f.write(f'slv{i}\t{s.name}\n')

# ---- once for the whole stack ----
t0 = time.time()
print('[setup 1/3] DEM')
dem = create_dem(a.master, out, a.dem_file)

print('[setup 2/3] master geometry (rdr2geo)')
geom_txt = out / 'master_geometry.txt'
if geom_txt.exists():
    geom = Path(geom_txt.read_text().strip())
else:
    geom = run_geometry(a.master, dem, out / 'master_geometry')
    geom_txt.write_text(str(geom))

print('[setup 3/3] restored master')
mst = out / f'mst_{mdate}.restored.tif'
if not mst.exists():
    tmp = mst.with_name('tmp_' + mst.name)
    apply_spotlight_phase_restoration(a.master, geom, tmp)
    tmp.rename(mst)
print(f'setup done in {time.time() - t0:.0f} s')

# ---- per secondary ----
for i, sec in enumerate(secs, 1):
    final = out / f"slv{i}_{sec.stem.split('_')[5][:8]}.tif"
    if final.exists():
        print(f'slv{i}: already done, skipping'); continue
    work = out / f'work_slv{i}'
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True)
    t1 = time.time()
    print(f'\n=== slv{i}/{len(secs)}: {sec.name} ===')
    try:
        rg_off, az_off = run_geo2rdr(sec, geom, work)
        coarse = work / 'coarse_resampled.tif'
        resample_slc(a.master, sec, rg_off, az_off, coarse, flatten=False)
        az_fine, rg_fine = compute_fine_offsets(a.master, coarse, work)
        rg_c, az_c = combine_offsets(rg_off, az_off, rg_fine, az_fine, work / 'combined_offsets')
        deramped = work / 'secondary.coregistered.deramped.tif'
        resample_slc(a.master, sec, rg_c, az_c, deramped, flatten=False)
        tmp = final.with_name('tmp_' + final.name)
        apply_spotlight_phase_restoration(sec, geom, tmp, data_file=deramped)
        tmp.rename(final)
        shutil.rmtree(work)                    # drop the intermediates, keep only the final file
        print(f'slv{i} done in {time.time() - t1:.0f} s -> {final}')
    except Exception:
        traceback.print_exc()
        print(f'slv{i} FAILED, work folder kept for inspection: {work}')

print(f'\nAll done in {time.time() - t0:.0f} s')
