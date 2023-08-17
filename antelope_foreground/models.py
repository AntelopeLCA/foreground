"""
Defining pydantic models for foreground types- in preparation for writing the oryx API (aka. Antelope v2 foreground)

We need:

 Fragment(Entity) <- full record
 FragmentRef(EntityRef) <- minimal (but not even a name?
 FragmentLink (for tree)
 FragmentFlow (for traversal)

and that's probably it

"""
from typing import Dict, Optional, List
from antelope.models import ResponseModel, EntityRef, Entity, FlowEntity
from antelope.xdb_tokens import ResourceSpec
from antelope import comp_dir


class Anchor(ResponseModel):
    """
    An anchor is either: a terminal node designation (i.e. origin + ref) or a context, and a descent marker.
    and cached LCIA scores

    Use FlowTermination.to_anchor(term, ..) to produce
    """
    node: Optional[EntityRef]
    anchor_flow: Optional[EntityRef]
    context: Optional[List[str]]
    descend: bool
    score_cache: Optional[Dict[str, float]]

    @property
    def type(self):
        if self.node:
            return 'node'
        elif self.context:
            return 'context'
        else:
            return 'cutoff'

    @property
    def is_null(self):
        return not bool(self.node or self.context)

    @classmethod
    def null(cls):
        return cls(descend=True)

    def _term_flow_block(self):
        if self.anchor_flow:
            if self.anchor_flow.origin == self.node.origin:
                return self.anchor_flow.entity_id
            else:
                return {
                    'origin': self.anchor_flow.origin,
                    'externalId': self.anchor_flow.entity_id
                }

    def serialize(self):
        """
        emulates FlowTermination.serialize()
        :return:
        """
        if self.context:
            j = {
                'origin': 'foreground',
                'context': self.context[-1]
            }
        else:
            j = {
                'origin': self.node.origin,
                'externalId': self.node.entity_id
            }
        j['descend'] = self.descend
        tfb = self._term_flow_block()
        if tfb:
            j['termFlow'] = tfb
        j['scoreCache'] = self.score_cache
        return j


class FragmentRef(EntityRef):
    """
    From EntityRef, inherits: origin, entity_id (<-external_ref), optional entity_type
    """
    entity_type: str = 'fragment'
    flow: EntityRef
    direction: str
    name: str

    @classmethod
    def from_fragment(cls, fragment):
        if fragment.reference_entity is None:
            dirn = comp_dir(fragment.direction)
        else:
            dirn = fragment.direction
        return cls(origin=fragment.origin, entity_id=fragment.external_ref,
                   flow=EntityRef.from_entity(fragment.flow), direction=dirn, name=fragment['name'])


class FragmentEntity(Entity):
    """
    From Entity, inherits: origin, entity_id (<- external_ref), entity_type, properties
    """
    entity_type: str = 'fragment'
    flow: FlowEntity  # should be full entity or just a ref? this is a full return, it should be full
    direction: str
    parent: Optional[str]
    is_balance_flow: bool

    entity_uuid: str  # we need uuid for consistency since we are running the same LcForeground on the backend

    exchange_values: Dict[str, float]

    anchors: Dict[str, Optional[Anchor]]

    @classmethod
    def from_entity(cls, fragment, save_unit_scores=False, **kwargs):
        if fragment.reference_entity is None:
            dirn = comp_dir(fragment.direction)
        else:
            dirn = fragment.direction
        j = fragment.serialize(**kwargs)
        evs = j.pop('exchangeValues')
        evs['cached'] = evs.pop('0')
        evs['observed'] = evs.pop('1')
        terms = {}
        for k, v in fragment.terminations():
            if k is None:
                k = 'default'
            terms[k] = v.to_anchor(save_unit_scores=save_unit_scores)
        return cls(origin=fragment.origin, entity_id=fragment.external_ref, properties=j.pop('tags'),
                   entity_uuid=fragment.uuid,
                   flow=FlowEntity.from_flow(fragment.flow), direction=dirn,
                   parent=j.pop('parent'), is_balance_flow=j.pop('isBalanceFlow'),
                   exchange_values=evs, anchors=terms)

    def _serialize_evs(self):
        d = dict(**self.exchange_values)
        d["0"] = d.pop('cached')
        d["1"] = d.pop('observed')
        return d

    def _serialize_terms(self):
        terms = dict()
        for k, v in self.anchors.items():
            if v is None:
                terms[k] = {}
            else:
                terms[k] = v.serialize()
        return terms

    def serialize(self):
        """
        This emulates LcFragment.serialize()
        :return:
        """
        j = {
            'entityType': self.entity_type,
            'externalId': self.entity_id,
            'entityId': self.entity_uuid,
            'parent': self.parent
        }
        if self.flow.origin == self.origin:
            j['flow'] = self.flow.entity_id
        else:
            j['flow'] = '%s/%s' % (self.flow.origin, self.flow.entity_id)
        j['direction'] = self.direction
        j['isPrivate'] = False
        j['isBalanceFlow'] = self.is_balance_flow,
        j['exchangeValues'] = self._serialize_evs(),
        j['terminations'] = self._serialize_terms(),
        j['tags'] = dict(**self.properties)
        return j


class FragmentBranch(ResponseModel):
    """
    Used to construct a tree diagram. Reports exchange values only, can be null (if not observable), and no node weights
    (because no traversal)
    """
    parent: Optional[str]
    node: FragmentRef
    name: str
    group: str  # this is the StageName, used for aggregation.. the backend must set / user specify / modeler constrain
    magnitude: Optional[float]
    unit: str
    anchor: Optional[Anchor]
    is_cutoff: bool
    is_balance_flow: bool

    @classmethod
    def from_fragment(cls, fragment, scenario=None, observed=False, group='StageName', save_unit_scores=False):
        """

        :param fragment:
        :param scenario:
        :param observed:
        :param group:
        :param save_unit_scores: score_cache must generally not be returned unless some aggregation condition is met
        :return:
        """
        if fragment.observable(scenario):
            mag = fragment.exchange_value(scenario, observed)
        else:
            mag = None
        if fragment.is_balance:
            print(' ## Balance Flow ## %s' % fragment)
        if fragment.reference_entity is None:
            parent = None
        else:
            parent = fragment.reference_entity.external_ref
        term = fragment.termination(scenario)
        anchor = term.to_anchor(save_unit_scores=save_unit_scores)
        if anchor is None and len(list(fragment.child_flows)) == 0:
            cutoff = True
        else:
            cutoff = False
        return cls(parent=parent, node=FragmentRef.from_fragment(fragment), name=term.name,
                   group=fragment.get(group, ''),
                   magnitude=mag, unit=fragment.flow.unit, is_balance_flow=fragment.is_balance,
                   anchor=anchor, is_cutoff=cutoff)


class FragmentFlow(ResponseModel):
    """
    A FragmentFlow is a record of a link in a traversal. Current controversy: when a flow magnitude or anchor is
    determined by a scenario specification, the FragmentFlow needs to report that.

    Also: whether foreground nodes (anchor = self) actually have anchors (decision: no, the 'foreground is self'
    designation is actually a hack and is redundant. the relevant trait is whether it has child flows, which can be
    known by the constructor)

    hmm except all FragmentFlows have anchors. I think we need to preserve the anchor-is-self, and simply test for it
    when doing operations.

    """
    parent: Optional[str]
    node: FragmentRef
    name: str
    group: str  # this is the StageName, used for aggregation.. the backend must set / user specify / modeler constrain
    magnitude: float
    scenario: Optional[str]
    unit: str
    node_weight: float
    anchor: Optional[Anchor]
    anchor_scenario: Optional[str]
    is_conserved: bool

    @classmethod
    def from_fragment_flow(cls, ff, group='StageName', save_unit_scores=False):
        """
        The ff is a FragmentFlow generated during a traversal (or tree crawl)
        :param ff:
        :param group:
        :param save_unit_scores: score_cache must generally not be returned unless some aggregation condition is met
        :return:
        """
        if ff.fragment.reference_entity is None:
            parent = None
        else:
            parent = ff.fragment.reference_entity.external_ref
        scen, a_scen = ff.match_scenarios
        if scen in (1, '1', True):
            scen = 'observed'
        return cls(parent=parent, node=FragmentRef.from_fragment(ff.fragment), name=ff.name,
                   group=ff.fragment.get(group, ''),
                   magnitude=ff.magnitude, scenario=scen, unit=ff.fragment.flow.unit, node_weight=ff.node_weight,
                   is_conserved=ff.is_conserved,
                   anchor=ff.term.to_anchor(save_unit_scores=save_unit_scores), anchor_scenario=a_scen)


"""
Foreground serialization

1- foreground serialization has shown to be sufficient to reproduce models
2- thus, formalize the serialization


"""


class MicroCf(ResponseModel):
    ref_quantity: str
    value: Dict[str, float]  # locale, CF


class Compartment(ResponseModel):
    name: str
    parent: Optional[str]
    sense: Optional[str]
    synonyms: List[str]


class Flowable(ResponseModel):
    name: str
    synonyms: List[str]


class TermManager(ResponseModel):
    Characterizations: Dict[str, Dict[str, Dict[str, MicroCf]]]  # query qty, flowable, compartment
    Compartments: List[Compartment]
    Flowables: List[Flowable]


'''
class LcTermination(ResponseModel):
    """
    these became anchors
    """
    externalId: str
    origin: str
    direction: Optional[str]
    termFlow: Optional[str]
    descend: Optional[str]
    context: Optional[str]
'''


class LcModel(ResponseModel):
    fragments: List[FragmentEntity]

    @classmethod
    def from_reference_fragment(cls, fragment, save_unit_scores=False):
        """
        Replicates the save_fragments method of the LcForeground provider
        for packing prior to transmission over HTTP
        """
        def _recurse_frags(f):
            _r = [f]
            for _x in f.child_flows:  # child flows are already ordered
                _r.extend(_recurse_frags(_x))
            return _r

        fragments = [FragmentEntity.from_entity(k, save_unit_scores=save_unit_scores) for k in _recurse_frags(fragment)]
        return cls(fragments=fragments)

    def serialize(self):
        """
        Replicates the LcFragment.serialize() operation
        for unpacking and storing upon receipt over HTTP
        :return:
        """
        return {
            'fragments': [
                k.serialize() for k in self.fragments
            ]
        }


class LcForeground(ResponseModel):

    catalogNames: Dict[str, List[str]]  #
    dataSource: str  #
    dataSourceType: str  #
    flows: List[Dict]  #
    initArgs: Dict  #
    quantities: List[Dict]  #
    termManager: Optional[TermManager]  #
    models: List[LcModel]
    resources: List[ResourceSpec]

    @classmethod
    def from_foreground_archive(cls, ar, save_unit_scores=False):
        """
        A simple function to construct a serialized foreground for transmission to an oryx server
        :param ar: an LcForeground archive
        :return: an LcForeground model
        """
        j = ar.serialize(characterizations=True, values=True)
        ms = [LcModel.from_reference_fragment(f, save_unit_scores=save_unit_scores) for f in ar.fragments()]
        rs = []
        return cls(resources=rs, models=ms, **j)
