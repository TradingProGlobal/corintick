"""
Contains all the serialization/compression related functions
"""
import hashlib
import io
import logging
import re
from collections import OrderedDict
from typing import Iterable, Sequence, Union

import lz4
import numpy as np
import pandas as pd
from bson import Binary, SON, InvalidBSON

logger = logging.getLogger('corintick')
MAX_BSON_SIZE = 2 ** 24  # 16 MB

def _serialize_array(arr: np.ndarray) -> bytes:
    """
    Serializes array using Numpy's native serialization functionality and
    compresses utilizing lz4's high compression algorithm.
    Arrays are serialized to C format and should be relatively easily to reverse
    engineer to other languages.
    Reference: https://docs.scipy.org/doc/numpy/neps/npy-format.html
    :param arr: Numpy array
    :return: Compressed bytes
    """
    if arr.dtype == np.dtype('O'):
        logger.warning('Attemping to serialize a Python object')
    with io.BytesIO() as f:
        np.save(f, arr)
        f.seek(0)
        output = f.read()
    return lz4.block.compress(output, mode='high_compression')


def _deserialize_array(data: bytes) -> np.ndarray:
    """
    Takes raw binary compressesed/serialized retrieved from MongoDB
    and decompresses/deserializes it, returning the original Numpy array
    :param data: LZ4-compressed binary blob
    :return: Numpy array
    """
    return np.load(io.BytesIO(lz4.block.decompress(data)))


def _make_bson_column(col: Union[pd.Series, pd.DatetimeIndex]) -> dict:
    """
    Compresses dataframe's column/index and returns a dictionary
    with BSON blob column and some metadata.
    :param arr: Input column/index
    :return: Column data dictionary
    """
    data = Binary(_serialize_array(col.values))
    sha1 = Binary(hashlib.sha1(data).digest())
    dtype = str(col.dtype)
    size = len(data)
    return {'data': data, 'dtype': dtype, 'sha1': sha1, 'size': size}


def _make_bson_doc(uid: str, df: pd.DataFrame, metadata) -> SON:
    """
    Takes a DataFrame and makes a BSON document ready to be inserted
    into MongoDB. Given Conritick's focus on timeseries data, the input
    DataFrame index must be a DatetimeIndex.
    Column names are kept and saved as strings.
    Index name is explicitly discarded and not saved.

    :param uid: Unique ID for the timeseries represented by the input DataFrame
    :param df: Input DataFrame
    :param metadata: Any BSON-able objects to be attached to document as metadata
    :return: BSON document
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError('DataFrame index is not DatetimeIndex')

    mem_usage = df.memory_usage().sum()
    df = df.sort_index(ascending=True)
    # Remove invalid MongoDB field characters
    # TODO: enforce timezone
    df = df.rename(columns=lambda x: re.sub('\.', '', str(x)))
    index = _make_bson_column(df.index)
    columns = SON()
    for col in df.columns:
        columns[col] = _make_bson_column(df[col])

    nrows = len(df)
    binary_size = sum([columns[col]['size'] for col in df.columns])
    binary_size += index['size']
    compression_ratio = binary_size / mem_usage
    if binary_size > 0.95 * MAX_BSON_SIZE:
        msg = f'Binary data size is too large ({binary_size:,} / {compression_ratio:.1%})'
        logger.warning(msg)
        raise InvalidBSON(msg, compression_ratio)
    logger.info(f'{uid} document: {binary_size:,} bytes ({compression_ratio:.1%}), {nrows} rows')
    add_meta = {'nrows': nrows, 'binary_size': binary_size}
    metadata = {**metadata, **add_meta}

    doc = SON([
        ('uid', uid),
        ('start', df.index[0]),
        ('end', df.index[-1]),
        ('metadata', metadata),
        ('index', index),
        ('columns', columns)])

    return doc


def make_bson_docs(uid, df, metadata, max_size=MAX_BSON_SIZE * 4):
    """
    Wrapper around ``_make_bson_doc``.
    Since BSON documents can't be larger than 16 MB, this function makes sure
    that the input DataFrame is properly split into smaller chunks that can be
    inserted into MongoDB. An initial compressibility factor of >4x (memory usage <64MB)
    is assumed and recursively updated if invalid BSON is generated.

    :param uid: Unique ID for the timeseries represented by the input DataFrame
    :param df: Input DataFrame
    :param metadata: Any BSON-able objects to be attached to document as metadata
    :param max_size: Initial maximum DataFrame memory usage
    :return: List of BSON documents
    """

    def split_dataframes(large_df: pd.DataFrame, size) -> Sequence[pd.DataFrame]:
        mem_usage = large_df.memory_usage().sum()
        split_num = np.ceil(mem_usage / size)
        return np.array_split(large_df, split_num)

    docs = []
    for sub_df in split_dataframes(df, size=max_size):
        try:
            doc = _make_bson_doc(uid, sub_df, metadata)
            docs.append(doc)
        except InvalidBSON as e:
            new_max_size = 0.95 *  MAX_BSON_SIZE / e.args[1]
            assert new_max_size > MAX_BSON_SIZE * 0.8
            logger.warning(f'Reducing max DataFrame split max_size to {new_max_size:,}')
            return make_bson_docs(uid, df, metadata, max_size=new_max_size)
    return docs



def _build_dataframe(doc: SON) -> pd.DataFrame:
    """
    Builds DataFrame from passed BSON document. Input BSON document must
    match schema defined at `make_bson_doc`.
    :param doc: BSON document
    :return: DataFrame
    """
    index = pd.Index(_deserialize_array(doc['index']['data']))
    columns = [_deserialize_array(col['data']) for col in doc['columns'].values()]
    names = doc['columns'].keys()
    df = pd.DataFrame(index=index, data=OrderedDict(zip(names, columns)))
    return df


def build_dataframe(docs: Iterable[SON]) -> pd.DataFrame:
    """
    Concatenates multiple documents of the same DataFrame
    :param docs:
    :return:
    """
    df: pd.DataFrame = pd.concat([_build_dataframe(doc) for doc in docs])
    return df.sort_index()
