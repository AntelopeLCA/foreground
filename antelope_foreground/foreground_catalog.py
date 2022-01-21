from antelope_core.archives import InterfaceError
from antelope_core.catalog import LcCatalog
from .foreground_query import ForegroundQuery, ForegroundNotSafe

from shutil import rmtree
import os


class BackReference(Exception):
    """
    trying to instantiate a foreground that's currently being loaded
    """
    pass


class ForegroundCatalog(LcCatalog):
    """
    Adds the ability to create (and manage?) foreground resources
    """

    '''
    ForegroundCatalog
    '''
    _fg_queue = set()  # fgs we are *currently* opening

    def is_in_queue(self, home):
        """
        This tells us whether the foreground named 'home' is actively being instantiated
        :param home:
        :return:
        """
        return home in self._fg_queue

    '''
    def delete_foreground(self, ref):
        """
        
        :param ref: 
        :return: 
        """
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
        if localpath:
            if os.path.exists(localpath):
                del_path = localpath + '-DELETED'
                if os.path.exists(del_path):
                    rmtree(del_path)
                os.rename(abs_path, del_path)
        dels = [k for k in self._resolver.resolve(ref, interfaces='foreground')]
        """
        dels = [k for k in self._resolver.resolve(ref, interfaces='foreground')]
        for k in dels:
            self.delete_resource(k, delete_source=True, delete_cache=True)
    '''

    def gen_interfaces(self, origin, itype=None, strict=False, ):
        """
        Override parent method to also create local backgrounds
        :param origin:
        :param itype:
        :param strict:
        :return:
        """
        if origin in self.foregrounds:
            for res in self._sorted_resources(origin, itype, strict):
                self._fg_queue.add(origin)
                res.check(self)
                self._fg_queue.remove(origin)
                try:
                    yield res.make_interface(itype)
                except InterfaceError:
                    continue
        else:
            for k in super(ForegroundCatalog, self).gen_interfaces(origin, itype=itype, strict=strict):
                yield k

    def foreground(self, ref, path=None, quiet=True, reset=False, delete=False):
        """
        Creates or activates a foreground resource and returns an interface to that resource.
        By default creates in a subdirectory of the catalog root with the ref as the folder
        :param ref:
        :param path:
        :param quiet:
        :param reset:
        :param delete:
        :return:
        """
        if ref in self._fg_queue:
            raise BackReference(ref)

        if path is None:
            path = os.path.join(self._rootdir, ref)  # should really sanitize this somehow
            # localpath = ref
        else:
            if os.path.isabs(path):
                pass
                # localpath = None
            else:
                # localpath = path
                path = os.path.join(self._rootdir, path)


        abs_path = os.path.abspath(path)
        local_path = self._localize_source(abs_path)

        try:
            res = next(self._resolver.resolve(ref, interfaces='foreground'))
        except StopIteration:
            res = self.new_resource(ref, local_path, 'LcForeground', interfaces=['index', 'foreground', 'quantity'],
                                    quiet=quiet)

        if reset:
            res.remove_archive()

        if reset:
            self._queries.pop(ref, None)

        self._fg_queue.add(ref)
        res.check(self)
        self._fg_queue.remove(ref)

        fg = res.make_interface('foreground')
        if ref not in self._queries:
            self._queries[ref] = ForegroundQuery(ref, catalog=self)

        return fg

    @property
    def foregrounds(self):
        f = set()
        for k in self.interfaces:
            org, inf = k.split(':')
            if inf == 'foreground' and org not in f:
                yield org
                f.add(org)

    def assign_new_origin(self, old_org, new_org):
        """
        This only works for certain types of archives. Foregrounds, in particular. but it is hard to say what else.
        What needs to happen here is:
         - first we retrieve the archive for the ref (ALL archives?)
         - then we call set_origin() on the archive
         - then we save the archive
         - then we rename the resource file
         = actually we just rewrite the resource file, since the filename and JSON key have to match
         = since we can't update resource origins, it's easiest to just blow them away and reload them
         = but to save time we should transfer the archives from the old resource to the new resource
         = anyway, it's not clear when we would want to enable this operation in the first place.
         * so for now we leave it
        :param old_org:
        :param new_org:
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
                    print('Saving resource configuration for %s' % res.origin)
                    res.save(self)

            else:
                if res.internal:
                    print('Deleting unconfigurable internal resource for %s\nsource: %s' % (res.origin, abs_src))
                    self.delete_resource(res, delete_source=True)
                else:
                    print('Unable to apply configuration to resource for %s\nsource: %s' % (res.origin, res.source))

    def delete_foreground(self, foreground, really=False):
        res = self.get_resource(foreground, 'foreground')
        self.delete_resource(res)
        abs_src = self.abs_path(res.source)
        if really:
            rmtree(abs_src)
        else:
            del_path = abs_src + '-DELETED'
            if os.path.exists(del_path):
                rmtree(del_path)

            os.rename(abs_src, del_path)
            
    def query(self, origin, strict=False, refresh=False, **kwargs):
        if origin in self.foregrounds:
            if origin not in self._queries:
                # we haven't loaded this fg yet, so
                raise ForegroundNotSafe(origin)
            if origin in self._fg_queue:
                raise BackReference(origin)
            if refresh or (origin not in self._queries):
                self._queries[origin] = ForegroundQuery(origin, catalog=self, **kwargs)
            return self._queries[origin]

        return super(ForegroundCatalog, self).query(origin, strict=strict, **kwargs)
