import os
import tifffile
import glob
from xml.etree import ElementTree
from itertools import product
from aicspylibczi import CziFile
import xmltodict
from lxml import etree
from datetime import datetime


def extension(path: str, *, lower: bool = True):
    _, ext = os.path.splitext(path)
    return ext.lower() if lower else ext


def replace_extension(path: str, ext: str):
    base, _ = os.path.splitext(path)
    return base + os.path.extsep + ext


def write_exposure_times(meta_dict, i_cycle, outdir):
    """Write exposure_times.txt. Infer the exposure times from given meta-xml
    given in dictionary format.
    Return path to saved exposure_times.txt file."""
    # Metadata►Information►Image►Dimensions►Channels►Channel►0►ExposureTime
    d_channel = meta_dict['ImageDocument']['Metadata']['Information']['Image'][
        'Dimensions']['Channels']['Channel']
    exptime = []
    default_scaling = 1E6
    for i in range(len(d_channel)):
        etime = float(d_channel[i]['ExposureTime'])/default_scaling
        if etime.is_integer():
            exptime.append(int(etime))
        else:
            exptime.append(etime)

    exp_filename = 'exposure'
    txt = '.txt'
    # Check if exposure_times.txt already exist, if yes write exp-times into
    # new file: exposure_times_{TIMESTAMP_NOW}.txt file
    if os.path.exists(os.path.join(outdir, exp_filename + txt)) and \
            i_cycle == 1:
        timestamp = datetime.now()
        exp_filename = exp_filename + '_' + timestamp.strftime(
            "%m%d%Y_%H%M%S") + txt
        raise Warning("exposure_times.txt already exist. New exposure_times "
                      "file is created with the name '" + exp_filename +
                      "'.txt'")

    with open(os.path.join(outdir, exp_filename + txt), 'a') as filehandle:
        if i_cycle == 1:
            filehandle.write('Cycle,CH1,CH2,CH3,CH4 \n')
        filehandle.write(str(i_cycle))
        for listitem in exptime:
            filehandle.write(',%s' % listitem)
        filehandle.write('\n')

    exptime_path = os.path.join(outdir, exp_filename + txt)
    return exptime_path


# channel start from 1!!!
def czi_to_tiffs(basedir: str,
                 czi_filename: str,
                 outdir: str,
                 template: str = '1_{m:05}_Z{z:03}_CH{c:03}',
                 #'1_{m}_Z{z}_CH{c}',
                 *,
                 compression: str = 'zlib',
                 save_tile_metadata: bool = False):

    # list of czi-files
    czi_files = glob.glob(os.path.join(basedir, '*.czi'))
    num_cycles = len(czi_files)
    for i_cyc in range(1, num_cycles+1):
        # name of czi file without .czi extension
        basename, _ = os.path.splitext(czi_filename.format(i_cyc))

        czi = CziFile(os.path.join(basedir, basename + '.czi'))

        # output dir and foldername
        if not os.path.exists(outdir):
            os.makedirs(outdir, exist_ok=True)
        foldername = 'cyc{:03}_reg001'.format(int(basename[-2:]))  # Cyc{cycle:d}_reg{region:d}
        if not os.path.exists(os.path.join(outdir, foldername)):
            os.makedirs(os.path.join(outdir, foldername), exist_ok=True)

        # Extract and check dimensions
        # S: scene
        # T: time
        # C: channel
        # Z: focus position
        # M: tile index in a mosaic
        # Y, X: tile dimensions
        if czi.dims != 'STCZMYX':
            raise Exception('unexpected dimension ordering')
        # Scene, Timepoints, Channels, Z-slices, Mosaic, Height, Width
        S, T, C, Z, M, Y, X = czi.size
        if S != 1:
            raise Exception('only one scene expected')
        if T != 1:
            raise Exception('only one timepoint expected')

        # Check zero-based indexing
        dims_shape, = czi.dims_shape()
        # dims_shape is a dictionary which maps each dimension to its index
        # range
        for axis in dims_shape.values():
            if axis[0] != 0:
                raise Exception('expected zero-based indexing in CZI file')

        if not czi.is_mosaic():
            raise Exception('expected a mosaic image')

        # Save tiles
        tiles = []
        tile_meta = {}
        for m in range(M):
            # Get tile position
            tilepos = czi.read_subblock_rect(S=0, T=0, C=0, Z=0, M=m) # returns: (x, y, w, h)
            tiles.append(tilepos)
            # Iterate over channel and focus
            for (c, z) in product(range(C), range(Z)):
                # Get tile position
                cur_tilepos = czi.read_subblock_rect(S=0, T=0, C=c, Z=z, M=m)
                if cur_tilepos != tilepos:
                    raise Exception('tile rect expected to be independent of Z and'
                                    ' C dimensions')
                # Get tile metadata
                # _, cur_tile_meta = czi.read_subblock_metadata(unified_xml=True,
                # S=0, T=0, C=c, Z=z, M=m)#[0]
                cur_tile_meta = czi.read_subblock_metadata(unified_xml=True, S=0,
                                                           T=0, C=c, Z=z, M=m)
                # tile_meta[(c, z, m)] = cur_tile_meta[1]
                # Save tile as tiff
                # filename = template.format(c=c, z=z, m=m, basename=basename)
                # filename = os.path.join(outdir, filename)

                filename = template.format(c=c+1, z=z+1, m=m+1) # Codex format starts at 1!
                filename = os.path.join(outdir, foldername, filename)
                tile_data, tile_shape = czi.read_image(S=0, T=0, C=c, Z=z, M=m)
                tifffile.imwrite(filename + '.tif', tile_data, compression=compression)
                # Save tile metadata
                if save_tile_metadata:
                    cur_tile_meta.getroottree().write(filename + '.xml')

        # Extract & save metadata
        meta = czi.meta
        with open(os.path.join(outdir, basename + '.xml'), 'w') as f:
            f.write(ElementTree.tostring(meta, encoding='unicode'))

        # save exposure_times.txt for each cycle
        meta_dict = xmltodict.parse(etree.tostring(meta))
        write_exposure_times(meta_dict, i_cyc, outdir)

    print("...finished generation of .tif files and exposure.txt file! "
          "...........")

    # Return shape and metadata
    return C, Z, tiles, meta, tile_meta
