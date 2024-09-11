from itertools import chain
import logging

from antelope import EntityNotFound, comp_dir, BackgroundRequired
from ..interfaces.iforeground import AntelopeForegroundInterface  # , ForegroundRequired
from antelope_core.implementations import BasicImplementation
from antelope_core.implementations.quantity import UnknownRefQuantity

from antelope_core.entities.xlsx_editor import XlsxArchiveUpdater
from antelope_core.contexts import NullContext
from antelope_core.entities.quantities import new_quantity
from antelope_core.entities.flows import new_flow

from ..entities.fragments import LcFragment, InvalidParentChild, FragmentBranch
from ..entities.fragment_editor import create_fragment, clone_fragment, _fork_fragment, interpose
from ..models import ForegroundRelease, Anchor


class NotForeground(Exception):
    pass


class UnknownFlow(Exception):
    pass


class AntelopeBasicImplementation(BasicImplementation):
    def get_reference(self, key):
        entity = self._dereference_entity(key)
        if entity.entity_type == 'fragment':
            return [entity.reference()]
        return super(AntelopeBasicImplementation, self).get_reference(key)


class AntelopeForegroundImplementation(BasicImplementation, AntelopeForegroundInterface):
    """
    A foreground manager allows a user to build foregrounds.  This should work with catalog references, rather
    than actual entities.

    This interface should cover all operations for web tool

    To build a fragment, we need:
     * child flows lambda
     * uuid

     * parent or None

     * Flow and Direction (relative to parent)
     * cached exchange value (or 1.0)

     * external_ref is uuid always? unless set-- ForegroundArchive gets a mapping from external_ref to uuid

     * other properties: Name, StageName

    To terminate a fragment we need a catalog ref: origin + ref for:
     * to foreground -> terminate to self
     * to subfragment -> just give uuid
     * background terminations are terminations to background fragments, as at present
     * process from archive, to become sub-fragment
     * flow, to become fg emission

    Fragment characteristics:
     * background flag
     * balance flag

    Scenario variants:
     - exchange value
     - termination
    """
    # _count = 0
    # _frags_with_flow = defaultdict(set)  # we actually want this to be shared among
    # _recursion_check = None

    ''' # NOT YET
    def __getitem__(self, item):
        """
        Let's have some standard etiquette here, people
        :param item:
        :return:
        """
        return self.get_local(item)
    '''

    '''
    Add some useful functions from other interfaces to the foreground
    '''
    @property
    def delayed(self):
        return self._archive.delayed

    @property
    def unresolved(self):
        return self._archive.unresolved

    def catalog_ref(self, *args, **kwargs):
        return self._archive.catalog_ref(*args, **kwargs)
    
    def catalog_query(self, origin, **kwargs):
        return self._archive.catalog_query(origin, **kwargs)

    def apply_xlsx(self, xlsx, quiet=True):
        """
        This is kind of inside baseball as long as xls_tools is not public
        :param self: a resource
        :param xlsx: an Xlrd-like spreadsheet: __getitem__(sheetname); sheet.row(i), sheet.column(j), sheet.nrows, sheet.ncols
        :param quiet:
        :return: nothing to return- user already has the resource
        """
        with XlsxArchiveUpdater(self._archive, xlsx, quiet=quiet, merge='overwrite') as x:
            x.apply()

    def count(self, entity_type):
        return self._archive.count_by_type(entity_type)

    def flows(self, **kwargs):
        for f in self._archive.search('flow', **kwargs):
            yield f

    def targets(self, flow, direction, **kwargs):
        return self.fragments_with_flow(flow, direction, **kwargs)

    '''
    for internal / convenience use
    '''
    def get_canonical(self, quantity):
        """
        By convention, a foreground archive's Term Manager is the catalog's LCIA engine, which is the Qdb of record
        for the foreground.
        :param quantity:
        :return:
        """
        return self._archive.tm.get_canonical(quantity)

    def context(self, item):
        return self._archive.tm[item]

    '''
    def get_context(self, item):
        return self._archive.tm[item]
    '''

    def flowable(self, item):
        return self._archive.tm.get_flowable(item)

    ''' # outmoded by find_term?
    def _grounded_ref(self, ref, check_etype=None):
        """
        Accept either a string, an unresolved catalog ref, a resolved catalog ref, or an entity
        Return an entity or grounded ref
        :param ref:
        :param check_etype:
        :return:
        """
        if hasattr(ref, 'entity_type'):
            if (not ref.is_entity) and (not ref.resolved):  # unresolved catalog ref
                try:
                    ent = self.get(ref.external_ref)
                except EntityNotFound:
                    ent = self._archive.catalog_ref(ref.origin, ref.external_ref)
            else:  # entity or resolved catalog ref
                ent = ref
        else:  # stringable
            try:
                ent = self.get(ref)
            except EntityNotFound:
                ent = self.get_local(ref)
        if check_etype is not None and ent.entity_type != check_etype:
            raise TypeError('%s: Not a %s' % (ref, check_etype))
        return ent
    '''

    '''
    fg implementation begins here
    '''
    def fragments(self, *args, show_all=False, **kwargs):
        if hasattr(self._archive, 'fragments'):
            # we only want reference fragments by default
            for f in self._archive.fragments(*args, show_all=show_all, **kwargs):
                yield f
        else:
            raise NotForeground('The resource does not contain fragments: %s' % self._archive.ref)

    def frag(self, string, **kwargs):
        """
        :param string:
        :param kwargs: many=False
        :return:
        """
        return self._archive.frag(string, **kwargs)

    def frags(self, string, knobs=True):
        """
        Show fragments whose names begin with
        :param string:
        :param knobs: [True] by default, only list named non-reference fragments (knobs).  If knobs=False,
        list reference fragments
        :return:
        """
        if knobs:
            for k in self.knobs():
                if k.external_ref.startswith(string):
                    yield k
        else:
            for k in self.fragments():
                if k.external_ref.startswith(string):
                    yield k

    '''
    Create and modify fragments
    '''
    def new_quantity(self, name, ref_unit=None, **kwargs):
        """

        :param name:
        :param ref_unit:
        :param kwargs:
        :return:
        """
        q = new_quantity(name, ref_unit, origin=self.origin, **kwargs)
        self._archive.add(q)
        return q

    def add_entity_and_children(self, *args, **kwargs):
        """
        This is invoked by xlsx_editor - putatively on an archive- when trying to create quantities that are found
        in the quantity db but not in the local archive.
        Then the model_updater replaces the archive with a foreground implementation, but as far as I can tell the
        foreground implementation NEVER had this method. So I don't understand how it was working before.
        :param args:
        :param kwargs:
        :return:
        """
        return self._archive.add_entity_and_children(*args, **kwargs)  # this is a hack

    def add_or_retrieve(self, external_ref, reference, name, group=None, strict=False, **kwargs):
        """
        Gets an entity with the given external_ref if it exists, , and creates it if it doesn't exist from the args.

        Note that the full spec is mandatory so it could be done by tuple.  With strict=False, an entity will be
        returned if it exists.
        :param external_ref:
        :param reference: a string, either a unit or known quantity
        :param name: the object's name
        :param group: used as context for flow
        :param strict: [False] if True it will raise a TypeError (ref) or ValueError (name) if an entity exists but
        does not match the spec.  n.b. I think I should check the reference entity even if strict is False but.. nah
        :return:
        """
        try:
            t = self.get(external_ref)
            if strict:
                if t.entity_type == 'flow':
                    if t.reference_entity != self.get_canonical(reference):
                        raise TypeError("ref quantity (%s) doesn't match supplied (%s)" % (t.reference_entity,
                                                                                           reference))
                elif t.entity_type == 'quantity':
                    if t.unit != reference:
                        raise TypeError("ref unit (%s) doesn't match supplied (%s)" % (t.unit, reference))
                if t['Name'] != name:
                    raise ValueError("Name (%s) doesn't match supplied(%s)" % (t['Name'], name))
            else:
                if t['Name'] != name:
                    t['Name'] = name
            for k, v in kwargs.items():
                if v is not None:
                    t[k] = v
            return t

        except EntityNotFound:
            try:
                cx = kwargs.pop('context', group)
                if group:
                    kwargs['group'] = group
                return self.new_flow(name, ref_quantity=reference, external_ref=external_ref, context=cx, **kwargs)
            except UnknownRefQuantity:
                # assume reference is a unit string specification
                return self.new_quantity(name, ref_unit=reference, external_ref=external_ref, group=group, **kwargs)

    def new_flow(self, name, ref_quantity=None, **kwargs):
        """

        :param name:
        :param ref_quantity: defaults to "Number of items"
        :param kwargs:
        :return:
        """

        if ref_quantity is None:
            ref_quantity = 'Number of items'
        try:
            ref_q = self.get_canonical(ref_quantity)
        except EntityNotFound:
            raise UnknownRefQuantity(ref_quantity)
        f = new_flow(name, ref_q, **kwargs)
        self._archive.add_entity_and_children(f)
        return self.get(f.link)

    def find_term(self, term_ref, origin=None, **kwargs):
        """

        :param term_ref:
        :param origin:
        :param kwargs:
        :return:
        """
        logging.warning('DEPRECATED: find_term()')
        if term_ref is None:
            return
        if hasattr(term_ref, 'entity_type'):
            if term_ref.entity_type == 'context':
                found_ref = term_ref
            elif (not term_ref.is_entity) and (not term_ref.resolved):  # unresolved catalog ref
                try:
                    found_ref = self.get(term_ref.external_ref)
                except EntityNotFound:
                    found_ref = term_ref  # why would we sub an unresolved catalog ref FOR an unresolved catalog ref?
            else:
                found_ref = term_ref
        else:
            # first context
            cx = self._archive.tm[term_ref]
            if cx not in (None, NullContext):
                found_ref = cx
            else:
                found_ref = self.get_local('/'.join(filter(None, (origin, term_ref))))
                ''' # this is now internal to get()
                except EntityNotFound:
                    if origin is None:
                        try:
                            origin, external_ref = term_ref.split('/', maxsplit=1)
                        except ValueError:
                            origin = 'foreground'
                            external_ref = term_ref

                        found_ref = self._archive.catalog_ref(origin, external_ref)
                    else:
                        found_ref = self._archive.catalog_ref(origin, term_ref)
                '''

        if found_ref.entity_type in ('flow', 'process', 'fragment', 'context'):
            return found_ref
        raise TypeError('Invalid entity type for termination: %s' % found_ref.entity_type)

    def post_entity_refs(self, entity_refs, **kwargs):
        """
        Not even sure this function is properly designed. do I *have* to construct a model just to post an existing
        entity to an existing foreground?
        :param entity_refs:
        :param kwargs:
        :return:
        """
        for ref in entity_refs:
            r = self._archive.catalog_ref(ref.origin, ref.external_ref, entity_type=ref.entity_type)
            if hasattr(ref, 'properties'):
                for k in ref.properties():
                    r[k] = ref[k]
            self._archive.add(r)

    def new_fragment(self, flow, direction, external_ref=None, **kwargs):
        """
        :param flow:
        :param direction:
        :param external_ref: if provided, observe and name the fragment after creation
        :param kwargs: uuid=None, parent=None, comment=None, value=None, units=None, balance=False;
          **kwargs passed to LcFragment
        :return:
        """
        if isinstance(flow, str):
            flow = self.get(flow)
        if flow.entity_type != 'flow':
            raise TypeError('%s: Not a %s' % (flow, 'flow'))
        frag = create_fragment(flow, direction, origin=self.origin, **kwargs)
        self._archive.add_entity_and_children(frag)
        if external_ref is not None:
            self.observe(frag, name=external_ref)
        return frag

    '''
    This is officially deprecated. let it break.
    def name_fragment(self, fragment, name, auto=None, force=None, **kwargs):
        return self._archive.name_fragment(fragment, name, auto=auto, force=force)
    '''

    def observe(self, fragment, exchange_value=None, units=None, scenario=None, anchor=None,
                anchor_node=None, anchor_flow=None,
                descend=None, name=None, auto=None, force=None,
                accept_all=None, termination=None, term_flow=None):
        """
        All-purpose method to manipulate fragments.
        :param fragment:
        :param exchange_value: default second positional param; exchange value being observed
        :param units: optional, modifies exchange value
        :param scenario: applies to exchange value and termination equially
        :param anchor: must be an Anchor or FlowTermination
        :param anchor_node: anchor target (node or context)
        :param anchor_flow: convert to flow on termination
        :param descend: set on anchor
        :param name: may not be used if a scenario is also supplied
        :param auto: auto-rename on name collision
        :param force: steal name on name collision
        :param accept_all: not allowed; caught and rejected
        :param termination: deprecated. assigned to anchor.
        :param term_flow: deprecated. assigned to anchor
        :param descend: deprecated, assigned to anchor
        :return:
        """
        anchor_target = None
        if anchor:
            if descend is None:
                descend = anchor.descend
            if isinstance(anchor, Anchor):
                if anchor.type == 'node':
                    anchor_target = anchor.node
                    if anchor_flow is None:
                        anchor_flow = anchor.anchor_flow.entity_id
                else:
                    anchor_target = self.get_context(anchor.context)
            else:
                if anchor.term_node:
                    anchor_target = anchor.term_node
                    if anchor_flow is None:
                        anchor_flow = anchor.term_flow

        if anchor_node:  # override
            anchor_target = anchor_node
        elif termination:
            anchor_target = termination
        if term_flow:
            anchor_flow = term_flow
        if accept_all is not None:
            print('%s: cannot "accept all"' % fragment)
        if name is not None:
            if scenario is None:  #
                if fragment.external_ref != name:
                    self._archive.name_fragment(fragment, name, auto=auto, force=force)
                    print('Naming fragment %s -> %s' % (fragment.external_ref, name))
                else:
                    # nothing to do
                    pass
            else:
                print('Ignoring fragment name under a scenario specification')
        if fragment.observable(scenario):
            self._archive.observe_ev(fragment, scenario=scenario, value=exchange_value, units=units)

        else:
            if exchange_value is not None:
                print('Note: Ignoring exchange value %g for unobservable fragment %s [%s]' % (exchange_value,
                                                                                              fragment.external_ref,
                                                                                              scenario))

        if anchor_target is not None:
            self._archive.observe_anchor(fragment, scenario, anchor_target, anchor_flow, descend=descend)

        return fragment.link

    def observe_unit_score(self, fragment, quantity, score, scenario=None, **kwargs):
        """

        :param fragment:
        :param quantity:
        :param score:
        :param scenario:
        :param kwargs:
        :return:
        """
        term = fragment.termination(scenario)
        term.add_lcia_score(quantity, score, scenario=scenario)

    def scenarios(self, fragment, recurse=True, **kwargs):
        if isinstance(fragment, str):
            fragment = self.get(fragment)

        for s in fragment.scenarios(recurse=recurse):
            yield s

    def nodes(self, origin=None, group='StageName', scenario=None, **kwargs):
        for f in self._archive.entities_by_type('fragment'):
            grp = f.get(group, '')
            for sc, t in f.terminations():
                if scenario is not None:
                    if sc != scenario:
                        continue
                if t.is_null or t.is_context:
                    continue
                if (origin is None and t.term_node.origin != self.origin) or t.term_node.origin == origin:
                    ev = f.exchange_value(sc)
                    yield FragmentBranch(f, t, grp, scenario=sc, magnitude=ev, is_cutoff=False)

    def knobs(self, search=None, param_dict=False, **kwargs):
        args = tuple(filter(None, [search]))
        for k in sorted(self._archive.fragments(*args, show_all=True), key=lambda x: x.external_ref):
            if k.is_balance:
                continue
            if k.is_reference:
                continue
            if k.external_ref == k.uuid:  # only generate named fragments
                continue
            if param_dict:
                yield k.parameters()
            else:
                yield k

    def fragments_with_flow(self, flow, direction=None, reference=True, background=None, **kwargs):
        """
        Requires flow identity
        :param flow:
        :param direction:
        :param reference: {True} | False | None
        :param background:
        :param kwargs:
        :return:
        """
        flow = self[flow]  # retrieve by external ref
        for f in self._archive.fragments_with_flow(flow):
            if background is not None:
                if f.is_background != background:
                    continue
            if direction is not None:
                if f.direction != direction:
                    continue
            if reference is False and f.parent is None:
                continue
            if reference and f.parent:
                continue
            yield f

    def clone_fragment(self, frag, tag=None, **kwargs):
        """

        :param frag: the fragment (and subfragments) to clone
        :param tag: string to attach to named external refs
        :param kwargs: passed to new fragment
        :return:
        """
        clone = clone_fragment(frag, tag=tag, **kwargs)
        self._archive.add_entity_and_children(clone)
        return clone

    def split_subfragment(self, fragment, replacement=None, descend=False, **kwargs):
        """
        Given a non-reference fragment, split it off into a new reference fragment, and create a surrogate child
        that terminates to it.

        without replacement:
        Old:   ...parent-->fragment
        New:   ...parent-->surrogate#fragment;   (fragment)

        with replacement:
        Old:   ...parent-->fragment;  (replacement)
        New:   ...parent-->surrogate#replacement;  (fragment);  (replacement)

        :param fragment:
        :param replacement: [None] if non-None, the surrogate is terminated to the replacement instead of the fork.
        :param descend: [False] on new term
        :return:
        """
        if fragment.reference_entity is None:
            raise AttributeError('Fragment is already a reference fragment')
        if replacement is not None:
            if replacement.reference_entity is not None:
                raise InvalidParentChild('Replacement is not a reference fragment')

        surrogate = _fork_fragment(fragment, comment='New subfragment')
        self._archive.add(surrogate)

        fragment.unset_parent()
        if replacement is None:
            surrogate.terminate(fragment, descend=descend)
        else:
            surrogate.terminate(replacement, descend=descend)

        return fragment

    def interpose(self, fragment, balance=True):
        inter = interpose(fragment)
        self._archive.add(inter)
        if balance:
            fragment.set_balance_flow()

        return inter

    def delete_fragment(self, fragment, **kwargs):
        """
        Remove the fragment and all its subfragments from the archive (they remain in memory)
        This does absolutely no safety checking.
        :param fragment:
        :return:
        """
        if isinstance(fragment, str):
            try:
                fragment = self.get(fragment)
            except EntityNotFound:
                return False
        self._archive.delete_fragment(fragment)
        for c in fragment.child_flows:
            self.delete_fragment(c)
        return True

    def save(self, release: ForegroundRelease = None, description=None, author=None, notes=None, major=False,
             save_unit_scores=None):
        if release is None:
            release = ForegroundRelease(major=major, description=description, author=author, notes=notes)
        self._archive.update_metadata(release)
        return self._archive.save(save_unit_scores=save_unit_scores)

    def tree(self, fragment, **kwargs):
        """

        :param fragment:
        :param kwargs:
        :return:
        """
        frag = self._archive.retrieve_or_fetch_entity(fragment)
        return frag.tree()

    def traverse(self, fragment, scenario=None, **kwargs):
        frag = self._archive.retrieve_or_fetch_entity(fragment)
        return frag.traverse(scenario, observed=True)

    def activity(self, fragment, scenario=None, **kwargs):
        top = self.top(fragment)
        if isinstance(top, LcFragment):
            return [f for f in top.traverse(scenario=scenario, **kwargs) if isinstance(f, LcFragment) and
                    f.top() is top]
        else:
            return top.activity(scenario=scenario, **kwargs)

    def clear_unit_scores(self, lcia_method=None):
        self._archive.clear_unit_scores(lcia_method)

    def clear_scenarios(self, terminations=True):
        for f in self._archive.entities_by_type('fragment'):
            f.clear_scenarios(terminations=terminations)

    def fragment_lcia(self, fragment, quantity_ref, scenario=None, refresh=False, mode=None, **kwargs):
        frag = self._archive.retrieve_or_fetch_entity(fragment)
        res = frag.top().fragment_lcia(quantity_ref, scenario=scenario, refresh=refresh, **kwargs)
        if mode == 'flat':  # 'detailed' doesn't make any sense when run locally
            return res.flatten()
        elif mode == 'stage':
            return res.aggregate()
        elif mode == 'anchor':
            return res.terminal_nodes()
        return res

    def create_process_model(self, process, ref_flow=None, set_background=None, StageName=None, **kwargs):
        """
        Create a fragment from the designated process model.  Creates a reference fragment whose exchange value
        is the reference value of the target, linked to a balance flow that is actually anchored to the target.
        Negative directions (i.e. ecoinvent's negative-valued treatment processes) are inverted and presented as
        having their natural direction.
        :param process:
        :param ref_flow:
        :param set_background:
        :param StageName: applied to both the reference and child
        :param kwargs: applied to the reference
        :return:
        """
        rx = process.reference(ref_flow)
        rv = process.reference_value(ref_flow)
        if rv < 0:  # put in to handle Ecoinvent treatment processes
            dirn = comp_dir(rx.direction)
            rv = abs(rv)
        else:
            dirn = rx.direction
        frag = self.new_fragment(rx.flow, dirn, value=rv, observe=True, **kwargs)
        node = self.new_fragment(rx.flow, frag.direction, parent=frag, balance=True)
        if StageName:
            frag['StageName'] = StageName
            node['StageName'] = StageName
        node.terminate(process, term_flow=rx.flow)
        # if set_background:
        #     frag.set_background()
        # self.fragment_from_exchanges(process.inventory(rx), parent=frag,
        #                              include_context=include_context, multi_flow=multi_flow)
        return frag

    def extend_process(self, fragment, scenario=None, include_context=False, **kwargs):
        if fragment.termination(scenario).is_fg and fragment.balance_flow:
            parent = fragment.balance_flow
        else:
            parent = fragment
        term = parent.termination(scenario)
        try:
            term.term_node.check_bg()
            if include_context:
                inv = chain(term.term_node.dependencies(ref_flow=term.term_flow),
                            term.term_node.cutoffs(ref_flow=term.term_flow),
                            term.term_node.emissions(ref_flow=term.term_flow))
            else:
                inv = chain(term.term_node.dependencies(ref_flow=term.term_flow),
                            term.term_node.cutoffs(ref_flow=term.term_flow))
        except BackgroundRequired:
            inv = term.term_node.inventory(term.term_flow)

        self.fragment_from_exchanges(inv, parent=parent,
                                     scenario=scenario,
                                     include_context=include_context,
                                     **kwargs)
        return fragment

    '''
    def extend_process_model(self, fragment, include_elementary=False, terminate=True, **kwargs):
        """
        "Build out" a fragment, creating child flows from its terminal node's intermediate flows
        :param fragment:
        :param include_elementary:
        :param terminate:
        :param kwargs:
        :return:
        """
        fragment.unset_background()
        process = fragment.term.term_node
        rx = fragment.term.term_flow
        for ex in process.inventory(rx):
            if not include_elementary:
                if ex.type in ('context', 'elementary'):
                    continue
            ch = self.new_fragment(ex.flow, ex.direction, value=ex.value, parent=fragment)
            ch.set_background()
            if ex.type in ('cutoff', 'self'):
                continue
            if terminate:
                ch.terminate(self._archive.catalog_ref(process.origin, ex.termination, entity_type='process'),
                             term_flow=ex.flow)
        fragment.observe(accept_all=True)
        return fragment
    '''
    def _grounded_entity(self, entity, **kwargs):
        if (not entity.is_entity) and (not entity.resolved):
            return self._archive.catalog_ref(entity.origin, entity.external_ref, **kwargs)
        else:
            return entity

    '''# Create or update a fragment from a list of exchanges.

    This needs to be an interface method.
    '''
    def fragment_from_exchanges(self, _xg, parent=None, ref=None, scenario=None,
                                term_dict=None,
                                set_background=None,
                                include_context=True):
        """
        If parent is None, first generated exchange is reference flow; and subsequent exchanges are children.
        Else, all generated exchanges are children of the given parent, and if a child flow exists, update it.
        The generated exchanges are assumed to be ordered, and are matched to child flows in the order originally created.

        This is all tricky if we expect it to work with both ExchangeRefs and actual exchanges (which, obviously, we
        should) because: ExchangeRefs may have only a string for process and flow, but Exchanges will have entities
        for each.  We need to get(flow_ref) and find_term(term_ref) but we can simply use flow entities and catalog
        refs if we have process.origin.  For now we will just swiss-army-knife it.

        And now we are adding auto-terminate to anything that comes back from fragments_with_flow

        :param _xg: Generates a list of exchanges or exchange references
        :param parent: if None, create parent from first exchange. If parent is provided, _xg must exclude references
        :param ref: if parent is created, assign it a name
        :param scenario: [None] specify the scenario under which to terminate child flows
        :param term_dict: [None] a mapping from EITHER existing termination OR flow external ref to target OR (target, term_flow) tuple
        :param set_background: [None] DEPRECATED / background is meaningless
        :param include_context: [False] whether to model context-terminated flows as child fragments
        :return:
        """
        if term_dict is None:
            term_dict = {}

        if set_background is not None:
            print('Warning: set_background is no longer meaningful- all terminations are background')
        if parent is None:
            try:
                x = next(_xg)
            except TypeError:
                x = _xg.pop(0)
            if ref is not None:
                parent = self[ref]

            if parent is None:
                parent = self.new_fragment(self._grounded_entity(x.flow), x.direction, value=x.value, units=x.unit,
                                           Name=str(x.process), **x.args)
                print('Creating new fragment %s (%s)' % (x.process.name, parent.uuid))
                if ref is not None:
                    self.observe(parent, name=ref)

            else:
                self.observe(parent, exchange_value=x.value, units=x.unit)

        _children = list(parent.child_flows)

        for y in _xg:
            """
            Determine flow specification
            """
            if hasattr(y.flow, 'entity_type') and y.flow.entity_type == 'flow':
                try:
                    flow = self._grounded_entity(y.flow)
                except EntityNotFound:
                    flow = y.flow  # groundless flow, better than throwing an exception
            else:
                flow = self[y.flow]
                if flow is None:
                    print('Skipping unknown flow %s' % y.flow)
                    continue
            """
            Determine / retrieve termination
            """
            if y.termination in term_dict:
                term = term_dict[y.termination]
            elif y.flow.external_ref in term_dict:
                term = term_dict[y.flow.external_ref]
            else:
                if y.type == 'context':
                    term = y.termination
                elif y.type == 'self':
                    term = None  # cutoff self-termination
                else:
                    try:
                        if hasattr(y.process, 'origin'):
                            term = self._archive.catalog_ref(y.process.origin, y.termination)
                        else:
                            term = self.get(y.termination)
                    except EntityNotFound:
                        term = None
            if isinstance(term, tuple):
                term, term_flow = term
            else:
                term_flow = None

            if term is not None and term.entity_type == 'context':
                if include_context is False:
                    continue
            elif term == y.process:
                # TODO: figure out why tuple(CatalogRef()) hangs
                term = None  # don't terminate self-term

            """
            Try and match the flow+direction spec to the ordered list of child flows 
            """
            if _children:
                try:
                    c_up = next(g for g in _children if g.flow == flow and g.direction == y.direction)

                    '''
                    #
                    # TODO: children_with_flow needs to be scenario aware
                    # TODO: Update fails with multi_flow when terms are not specified- bc there is no way to tell which
                    # record corresponds to which child.
                    if multi_flow:
                        c_up = next(parent.children_with_flow(flow, direction=y.direction, termination=term,
                                                              recurse=False))
                    else:
                        c_up = next(parent.children_with_flow(flow, direction=y.direction, recurse=False))
                    '''

                    # update value
                    v = y.value
                    if y.unit is not None:
                        v *= c_up.flow.reference_entity.convert(y.unit)

                    if c_up.exchange_value(scenario) != v:
                        print('Updating %s exchange value %.3f %s' % (c_up, y.value, y.unit or ''))

                        self.observe(c_up, exchange_value=y.value, units=y.unit, scenario=scenario)

                    '''# we certainly can
                    if multi_flow:
                        continue  # cannot update terms in the multi-flow case
                    '''
                    '''# However: we should NOT update already-terminated flows with "first available"
                    The current approach:
                     - if no termination is specified, hunt for one
                     - if a termination is supplied OR found in a hunt, go forward:
                       - if the termination doesn't match the existing one, replace it! very destructive
                    
                    RESOLVED: we should NOT hunt for terminations on a fragment update. REASON:
                     * fragments are built in an order selected by the modeler so as to determine which frags are found
                       in a "hunt". If we start updating based on hunt results, we can terminate intentionally-cutoff
                       frags.
                    The proposed new workflow:
                     = if a termination is specified:
                       - if it differs from the existing termination:
                         replace it!
                       - else, nothing to do
                     - else, do nothing. don't go hunting
                    '''
                    '''
                    if term is None:  
                        try:
                            term = next(self.fragments_with_flow(c_up.flow, c_up.direction))
                        except StopIteration:
                            pass
                    '''

                    # set term
                    if term is not None:
                        if term != c_up.term.term_node:
                            print('Updating %s termination %s' % (c_up, term))
                            c_up.clear_termination(scenario)
                            c_up.terminate(term, scenario=scenario, term_flow=term_flow, descend=False)  # none unless specified
                            '''
                            if term.entity_type == 'process' and set_background:
                                c_up.set_background()
                            '''

                    """
                    Propagate properties
                    """
                    for k, v in y.args.items():
                        c_up[k] = v

                    _children.remove(c_up)
                    continue

                except StopIteration:
                    print('No child flow found; creating new %s %s' % (flow, y.direction))
                    pass

            c = self.new_fragment(flow, y.direction, value=y.value, units=y.unit, parent=parent, **y.args)

            if term is None:
                try:  # go hunting for a term in the local foreground
                    term = next(self.fragments_with_flow(c.flow, c.direction))
                except StopIteration:
                    pass

            if term is not None:
                c.terminate(term, scenario=scenario, term_flow=term_flow, descend=False)  # already sets stage name
                '''
                if term.entity_type in ('process', 'flow'):  ##?? whaaa? process should terminate to reference, flow should terminate to itself
                    c.terminate(term, scenario=scenario, term_flow=c.flow)
                    if set_background:
                        c.set_background()
                else:
                    c.terminate(term, scenario=scenario)
                '''
            self.observe(c)  # use cached implicitly via fg interface

        return parent

    '''
    def make_fragment_trees(self, exchanges):
        """
        Take in a list of exchanges [that are properly connected] and build fragment trees from them. Return all roots.

        If an exchange's process has been encountered, it will be used as the parent.  Exchanges with null terminations
        become cutoff flows.

        If an exchange's process has not been encountered, AND its termination is null, it will become a reference
        fragment and be terminated to the process.

        Non-null-terminated exchanges whose processes have not been encountered cause an error.

        This function will only generate new fragments and will not affect any existing fragments.
        :param exchanges:
        :return:
        """
        roots = []
        parents = dict()
        for x in exchanges:
            if x.process.external_ref in parents:
                parent = parents[x.process.external_ref]
                # parent.unset_background()
                frag = self.new_fragment(x.flow, x.direction, parent=parent, **x.args)
                term = self.find_term(x.termination, origin=x.process.origin)
                if term is not None:
                    frag.terminate(term)
                    # frag.set_background()
            else:
                # unmatched flows become roots
                if x.termination is not None:
                    raise InvalidParentChild('Reference flow may not be terminated')
                frag = self.new_fragment(x.flow, x.direction, **x.args)
                roots.append(frag)
                frag.terminate(x.process)

            self.observe(frag, exchange_value=x.value)
            if frag.term.is_process:
                parents[frag.term.term_ref] = frag

        for r in roots:
            yield r
    '''
