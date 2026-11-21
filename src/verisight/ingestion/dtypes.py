"""Type inference that keeps pandas 2's column types.

pandas 3 gives text its own ``str`` dtype, and ``infer_objects`` moves text
columns to it. It also infers dates at microsecond resolution. Ingestion,
cleaning, profiling and the SQL engine read text from object columns of Python
strings and dates at nanosecond resolution, as pandas 2 left them, so the
columns keep those types.
"""

import pandas as pd


def infer_types(data: pd.DataFrame) -> pd.DataFrame:
    """Infer better types for object columns, as pandas 2 did.

    Text columns stay as they are. Dates are kept in nanoseconds, and a column
    with a date outside that range stays as Python objects.
    """
    inferred = data.infer_objects()
    for column in inferred.columns:
        dtype = inferred[column].dtype
        if isinstance(dtype, pd.StringDtype):
            inferred[column] = data[column]
        elif dtype.kind == "M" and dtype != "datetime64[ns]":
            try:
                inferred[column] = inferred[column].astype("datetime64[ns]")
            except pd.errors.OutOfBoundsDatetime:
                inferred[column] = data[column]
    return inferred
