from antelope import local_ref
from antelope_core.catalog import LcCatalog

from shutil import rmtree
import os
import re


class ForegroundCatalog(LcCatalog):
    """
    Adds the ability to create (and manage?) foreground resources
    """

    '''
    ForegroundCatalog
    '''

    def foreground(self, path, ref=None, quiet=True, reset=False, delete=False):
        """
        Creates or activates a foreground as a sub-folder within the catalog's root directory.  Returns a
        Foreground interface.
        :param path: either an absolute path or a subdirectory path relative to the catalog root
        :param ref: semantic reference (optional)
        :param quiet: passed to fg archive
        :param reset: [False] if True, clear the archive and create it from scratch, before returning the interface
        :param delete: [False] if True, delete the existing tree completely and irreversibly. actually just rename
        the directory to whatever-DELETED; but if this gets overwritten, there's no going back.  Overrides reset.
        :return:
        """
        if not os.path.isabs(path):
            path = os.path.join(self._rootdir, path)

        abs_path = os.path.abspath(path)
        local_path = self._localize_source(abs_path)
        _fg_path = re.sub('^\$CAT_ROOT', '', local_path)

        if delete:
            if os.path.exists(abs_path):
                del_path = abs_path + '-DELETED'
                if os.path.exists(del_path):
                    rmtree(del_path)
                os.rename(abs_path, del_path)
            dels = [k for k in self._resolver.resources_with_source(local_path)]
            for k in dels:
                self.delete_resource(k, delete_source=True, delete_cache=True)

        if ref is None:
            ref = local_ref(_fg_path, prefix='foreground')

        try:
            res = next(self._resolver.resources_with_source(local_path))
        except StopIteration:
            res = self.new_resource(ref, local_path, 'LcForeground', interfaces=['index', 'foreground', 'quantity'],
                                    quiet=quiet)

        if reset:
            res.remove_archive()
        res.check(self)

        return res.make_interface('foreground')

    def assign_new_ref(self, old_ref, new_ref):
        """
        This only works for certain types of archives. Foregrounds, in particular. but it is hard to say what else.
        What needs to happen here is:
         - first we retrieve the archive for the ref (ALL archives?)
         - then we call set_origin() on the archive
         - then we save the archive
         - then we rename the resource file
         = actually we just rewrite the resource file, since the filename and JSON key have to match
         = since we can't update resource references, it's easiest to just blow them away and reload them
         = but to save time we should transfer the archives from the old resource to the new resource
         = anyway, it's not clear when we would want to enable this operation in the first place.
         * so for now we leave it
        :param old_ref:
        :param new_ref:
        :return:
        """
        pass

    def configure_resource(self, reference, config, *args):
        """
        We must propagate configurations to internal, derived resources. This also begs for testing.
        :param reference:
        :param config:
        :param args:
        :return:
        """
        # TODO: testing??
        for res in self._resolver.resolve(reference, strict=False):
            abs_src = self.abs_path(res.source)
            if res.add_config(config, *args):
                if res.internal:
                    if os.path.dirname(abs_src) == self._index_dir:
                        print('Saving updated index %s' % abs_src)
                        res.archive.write_to_file(abs_src, gzip=True,
                                                  exchanges=False, characterizations=False, values=False)
                else:
                    print('Saving resource configuration for %s' % res.reference)
                    res.save(self)

            else:
                if res.internal:
                    print('Deleting unconfigurable internal resource for %s\nsource: %s' % (res.reference, abs_src))
                    self.delete_resource(res, delete_source=True)
                else:
                    print('Unable to apply configuration to resource for %s\nsource: %s' % (res.reference, res.source))
