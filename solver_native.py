import ctypes as ct
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parent
LIB = None
BUILD_ERROR = None
CHILD = ct.CFUNCTYPE(ct.c_int, ct.POINTER(ct.c_int32), ct.c_int, ct.c_int)
if os.environ.get('WORDLE_NO_NATIVE') != '1':
    source = ROOT / 'solver_native.c'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    directory = ROOT / '.native'
    target = directory / (digest + ('.dll' if os.name == 'nt' else '.so'))
    try:
        if not target.exists():
            compiler = shutil.which('gcc') or shutil.which('clang')
            if compiler is None:
                raise OSError('No C compiler found')
            directory.mkdir(exist_ok=True)
            temporary = directory / (target.stem + f'.{os.getpid()}.tmp' + target.suffix)
            subprocess.run([compiler, '-O3', '-std=c11', '-shared', '-static-libgcc',
                            str(source), '-o', str(temporary)], check=True,
                           capture_output=True, timeout=60)
            temporary.replace(target)
        LIB = ct.CDLL(str(target))
        ptr = ct.c_void_p
        LIB.last_best.argtypes = [ptr, ct.c_int, ptr, ct.c_int, ptr, ct.c_int, ct.c_int, ptr]
        LIB.last_best.restype = ct.c_int
        LIB.partition.argtypes = [ptr, ptr, ct.c_int, ptr, ptr]
        LIB.partition.restype = None
        LIB.rank_rows.argtypes = [ptr, ct.c_int, ptr, ct.c_int, ptr, ct.c_int, ptr]
        LIB.rank_rows.restype = None
        LIB.second_context.argtypes = []
        LIB.second_context.restype = ptr
        LIB.free_second_context.argtypes = [ptr]
        LIB.free_second_context.restype = None
        LIB.second_best.argtypes = [ptr, ct.c_int, ptr, ct.c_int, ptr, ct.c_int,
                                    ct.c_int, CHILD, ptr, ptr, ptr]
        LIB.second_best.restype = ct.c_int
    except (OSError, subprocess.SubprocessError) as error:
        BUILD_ERROR = str(error)
        LIB = None


def partition(table, ids, row):
    columns = np.asarray(ids, dtype=np.int32)
    if LIB is not None:
        output = np.empty(len(ids), dtype=np.int32)
        offsets = np.empty(244, dtype=np.int32)
        LIB.partition(table[row].ctypes.data, columns.ctypes.data, len(ids),
                      output.ctypes.data, offsets.ctypes.data)
        return [tuple(output[offsets[k]:offsets[k+1]].tolist())
                for k in np.flatnonzero(offsets[1:243] > offsets[:242])]
    codes = table[row, columns]
    return [tuple(columns[codes == k].tolist()) for k in np.unique(codes) if k != 242]


def rank(table, ids, rows):
    columns = np.asarray(ids, dtype=np.int32)
    scores = np.empty(len(rows), dtype=np.int32)
    if LIB is not None:
        LIB.rank_rows(table.ctypes.data, table.shape[1], columns.ctypes.data, len(ids),
                      rows.ctypes.data, len(rows), scores.ctypes.data)
    else:
        for i, row in enumerate(rows):
            counts = np.bincount(table[row, columns], minlength=243)
            scores[i] = counts @ counts
    return rows[np.argsort(scores, kind='stable')]


def last_best(table, ids, rows, best):
    columns = np.asarray(ids, dtype=np.int32)
    if LIB is not None:
        winner = ct.c_int(-1)
        value = LIB.last_best(table.ctypes.data, table.shape[1], columns.ctypes.data,
                              len(ids), rows.ctypes.data, len(rows), best, ct.byref(winner))
        return value, winner.value
    patterns = np.sort(table[np.ix_(rows, columns)], axis=1)
    failures = len(ids) - 1 - np.count_nonzero(patterns[:, 1:] != patterns[:, :-1], axis=1)
    offset = int(np.argmin(failures))
    value = int(failures[offset])
    return (value, int(rows[offset])) if value < best else (best, -1)


def second_best(table, ids, rows, best, evaluate, context):
    columns = np.asarray(ids, dtype=np.int32)
    errors = []

    @CHILD
    def callback(pointer, length, cap):
        try:
            child = tuple(np.ctypeslib.as_array(pointer, shape=(length,)).tolist())
            return evaluate(child, cap)
        except BaseException as error:
            errors.append(error)
            return -1

    winner, completed = ct.c_int(-1), ct.c_int(0)
    value = LIB.second_best(table.ctypes.data, table.shape[1], columns.ctypes.data,
                            len(ids), rows.ctypes.data, len(rows), best, callback,
                            context, ct.byref(winner), ct.byref(completed))
    if completed.value < 0:
        raise MemoryError('Native second-guess buffer allocation failed')
    return value, winner.value, completed.value, errors[0] if errors else None
