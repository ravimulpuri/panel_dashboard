from functools import wraps

try:
    # Import register decorators from pandas >= 0.23
    from pandas.api.extensions import (
        register_dataframe_accessor,
        register_series_accessor,
    )
except ImportError:
    from pandas import DataFrame, Series

    try:
        from pandas.core.accessor import AccessorProperty
    except ImportError:  # Pandas before 0.22.0
        from pandas.core.base import AccessorProperty

    # Define register decorators for pandas < 0.23
    class register_dataframe_accessor(object):
        """Register custom accessor on DataFrame."""

        def __init__(self, name):
            self.name = name

        def __call__(self, accessor):
            setattr(DataFrame, self.name, AccessorProperty(accessor, accessor))

    class register_series_accessor(object):
        """Register custom accessor on Series."""

        def __init__(self, name):
            self.name = name

        def __call__(self, accessor):
            setattr(Series, self.name, AccessorProperty(accessor, accessor))


def register_dataframe_method(method):
    """
    Register a function as a method attached to the Pandas DataFrame.
    Example
    -------
    @register_dataframe_method
    def print_column(df, col):
        '''Print the dataframe column given'''
        print(df[col])
    """

    def inner(*args, **kwargs):
        class AccessorMethod(object):
            def __init__(self, pandas_obj):
                self._obj = pandas_obj

            @wraps(method)
            def __call__(self, *args, **kwargs):
                return method(self._obj, *args, **kwargs)

        register_dataframe_accessor(method.__name__)(AccessorMethod)

        return method

    return inner()


def register_series_method(method):
    """
    Register a function as a method attached to the Pandas Series.
    """

    def inner(*args, **kwargs):
        class AccessorMethod(object):
            __doc__ = method.__doc__

            def __init__(self, pandas_obj):
                self._obj = pandas_obj

            @wraps(method)
            def __call__(self, *args, **kwargs):
                return method(self._obj, *args, **kwargs)

        register_series_accessor(method.__name__)(AccessorMethod)

        return method

    return inner()