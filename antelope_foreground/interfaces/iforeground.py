"""
I don't really want a foreground interface--- I want a foreground construction yard.  the query is not the right
route for this maybe?

I want to do the things in the editor: create and curate flows, terminate flows in processes, recurse on processes.

anything else?
child fragment flow generators and handlers. scenario tools.

scenarios currently live in the fragments- those need to be tracked somewhere. notably: on traversal, when parameters
are encountered.

Should that be here? how about monte carlo? where does that get done?

when do I go to bed?
"""

from antelope import ForegroundInterface


class ForegroundRequired(Exception):
    pass


_interface = 'foreground'


class AntelopeForegroundInterface(ForegroundInterface):
    """
    The bare minimum foreground interface allows a foreground to return terminations and to save anything it creates.
    erm "anchors"
    """
    '''
    Left to subclasses
    '''
    def fragments(self, show_all=False, **kwargs):
        if show_all:
            raise ValueError('Cannot retrieve non-parent fragments via interface')
        for i in self._perform_query(_interface, 'fragments', ForegroundRequired,
                                     **kwargs):
            yield self.make_ref(i)

    def top(self, fragment, **kwargs):
        """
        Return the reference fragment that is top parent of named fragment
        :param fragment:
        :param kwargs:
        :return:
        """
        return self.make_ref(self._perform_query(_interface, 'top', ForegroundRequired, fragment, **kwargs))

    def parent(self, fragment, **kwargs):
        """
        A foreground-specific hook for get_reference
        :param fragment:
        :param kwargs:
        :return:
        """
        return self.make_ref(self._perform_query(_interface, 'get_reference', ForegroundRequired, fragment, **kwargs))

    def frag(self, string, many=False, **kwargs):
        """
        Return the unique fragment whose ID starts with string.

        Default: If the string is insufficiently specific (i.e. there are multiple matches), raise
        :param string:
        :param many: [False] if true, return a generator and don't raise an error
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'frag', ForegroundRequired,
                                   string, many=many, **kwargs)

    def frags(self, string, **kwargs):
        """
        Among only named fragments, return fragments whose names (external_ref) begin with string
        :param string:
        """
        return self._perform_query(_interface, 'frags', ForegroundRequired,
                                   string, **kwargs)

    '''
    def name_fragment(self, fragment, name, auto=None, force=None, **kwargs):
        """
        Assign a fragment a non-UUID external ref to facilitate its easy retrieval.  I suspect this should be
        constrained to reference fragments.  By default, if the requested name is taken, a ValueError is raised
        :param fragment:
        :param auto: if True, if name is taken, apply an auto-incrementing numeric suffix until a free name is found
        :param force: if True, if name is taken, de-name the prior fragment and assign the name to the current one
        :return:
        """
        return self._perform_query(_interface, 'name_fragment', ForegroundRequired,
                                   fragment, name, **kwargs)
    '''

    '''
    def find_or_create_term(self, exchange, background=None):
        """
        Finds a fragment that terminates the given exchange
        :param exchange:
        :param background: [None] - any frag; [True] - background frag; [False] - foreground frag
        :return:
        """
        return self._perform_query(_interface, 'find_or_create_term', ForegroundRequired,
                                   exchange, background=background)
    '''
    def add_or_retrieve(self, external_ref, reference, name, group=None, **kwargs):
        """
        Gets an entity with the given external_ref if it exists, , and creates it if it doesn't exist from the args.

        Note that the full spec is mandatory so it could be done by tuple.
        :param external_ref:
        :param reference:
        :param name:
        :param group: None
        :param kwargs:
        :return:
        """
        return self.make_ref(self._perform_query(_interface, 'add_or_retrieve', ForegroundRequired,
                                                 external_ref, reference, name, group=group, **kwargs))

    def post_entity_refs(self, entity_refs, **kwargs):
        """
        Add entities to the foreground by reference. mostly useful when working with remote foregrounds.
        :param entity_refs:
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'post_entity_refs', ForegroundRequired,
                                   entity_refs, **kwargs)

    def create_fragment_from_node(self, process_ref, ref_flow=None, include_elementary=False):
        """
        a synonym for create_process_model
        :param process_ref: a ProcessRef
        :param ref_flow:
        :param include_elementary:
        :return:
        """
        return self._perform_query(_interface, 'create_process_model', ForegroundRequired,
                                   process_ref, ref_flow=ref_flow, include_elementary=include_elementary)

    def clone_fragment(self, frag, tag=None, **kwargs):
        """

        :param frag: the fragment (and subfragments) to clone
        :param kwargs: tag - appended to all named child fragments
        :return:
        """
        return self._perform_query(_interface, 'clone_fragment', ForegroundRequired,
                                   frag, tag=tag, **kwargs)

    def delete_fragment(self, fragment, **kwargs):
        """
        Remove the fragment and all its subfragments from the archive (they remain in memory)
        This does absolutely no safety checking.

        :param fragment:
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'delete_fragment', ForegroundRequired,
                                   fragment, **kwargs)

    def scenarios(self, fragment, recurse=True, **kwargs):
        """
        Return a recursive list
        :param fragment:
        :param recurse: [True] whether to include scenarios in child fragments
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'scenarios', ForegroundRequired,
                                   fragment, recurse=recurse, **kwargs)

    def nodes(self, origin=None, scenario=None, **kwargs):
        """
        Return non-trivial anchors in the current foreground, optionally filtered by origin
        :param origin: [None] if present, only return nodes whose anchor has the given origin
        :param scenario: [None] if present, only return nodes for the given scenario
        :return:
        """
        return self._perform_query(_interface, 'nodes', ForegroundRequired, origin=origin, scenario=scenario, **kwargs)

    def knobs(self, search=None, **kwargs):
        """
        Return a list of named fragments whose values can be observed to define scenarios.  Generates a list
        of non-reference fragments with names
        :return:
        """
        return self._perform_query(_interface, 'knobs', ForegroundRequired,
                                   search=search, **kwargs)

    def set_balance_flow(self, fragment, **kwargs):
        """
        This should get folded into observe
        Specify that a given fragment is a balancing flow for the parent node, with respect to the specified fragment's
        flow's reference quantity.

        :param fragment:
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'set_balance_flow', ForegroundRequired,
                                   fragment, **kwargs)

    def unset_balance_flow(self, fragment, **kwargs):
        """
        This should get folded into observe
        Specify that a given fragment's balance status should be removed.  The fragment's observed EV will remain at
        the most recently observed level.
        :param fragment:
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'unset_balance_flow', ForegroundRequired,
                                   fragment, **kwargs)

    def create_process_model(self, process, ref_flow=None, set_background=None, **kwargs):
        """
        Create a fragment from a process_ref.  If process has only one reference exchange, it will be used automatically.
        By default, a child fragment is created for each exchange not terminated to context, and exchanges terminated
        to nodes are so terminated in the fragment.
        :param process:
        :param ref_flow: specify which exchange to use as a reference
        :param set_background: [None] Deprecated. All terminations are "to background".
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'create_process_model', ForegroundRequired,
                                   process, ref_flow=ref_flow, **kwargs)

    def extend_process(self, fragment, scenario=None, include_context=False, **kwargs):
        """

        :param fragment:
        :param scenario:
        :param include_context:
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'extend_process', ForegroundRequired,
                                   fragment, scenario=scenario, include_context=include_context, **kwargs)

    def fragment_from_exchanges(self, exchanges, parent=None, include_context=False, **kwargs):
        """

        :param exchanges:
        :param parent: if parent is None, the first exchange is taken to be a reference fragment
        :param include_context: [False] if true, create subfragments terminating to context for elementary flows.
         otherwise leaves them unspecified (fragment LCIA includes unobserved exchanges)
        :param kwargs:
        :return:
        """
        return self._perform_query(_interface, 'fragment_from_exchanges', ForegroundRequired,
                                   exchanges, parent=parent, include_context=include_context, **kwargs)
