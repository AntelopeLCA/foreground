from .foreground import LcForeground, FOREGROUND_ENTITY_TYPES

def init_fcn(source, ref=None, **kwargs):
    """
    Returns an LcForeground implementation
    :param source: Filename to store the serialized A and B matrices in numpy [matlab] format.
    :param ref: semantic reference for the archive
    :param kwargs:
    :return: an LcForeground archive.
    """
    if ref is None:
        ref = 'test.free.background'
    return LcForeground(source, ref=ref, **kwargs)  # make_interface('background') to generate/access flat bg

