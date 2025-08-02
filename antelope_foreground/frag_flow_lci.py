from collections import defaultdict
from antelope import ExchangeRef


def frag_flow_lci(fragmentflows, scenario=None):
    """
    Aggregates LCI results recursively into a single set of exchanges.
    The way this works is pretty simple: we go over the traversal. For each node, if the term is a process,
    we grab its LCI, scale each flow by the node weight, and add to the defaultdict
    if the term is a fragment, we call self recursively and add the results to the defaultdict
    if the term is a context, we add it directly to the defaultdict
    if it's a cutoff, we skip
    :param fragmentflows:
    :param scenario: only used for remote calculation of subfragments
    :return:
    """
    lci = defaultdict(float)
    parent = None

    for ff in fragmentflows:
        if parent is None:
            # take first one
            parent = ff.fragment
        # _recursive_remote = False
        if ff.term.is_null:
            continue

        node_weight = ff.node_weight
        if node_weight == 0:
            continue

        if ff.term.direction == ff.fragment.direction:
            # if the directions collide (rather than complement), the term is getting run in reverse
            node_weight *= -1

        if ff.term.is_subfrag:
            if len(ff.subfragments) == 0:
                print(' THIS NEVER HAPPENS %s' % ff)
                sub_lci = ff.term.term_node.fragment_lci(scenario)  # this does not yet exist
            else:
                sub_lci = frag_flow_lci(ff.subfragments, scenario=ff.subfragment_scenarios)
        else:
            sub_lci = ff.term.unobserved_exchanges(threshold=1e-9)

        for k in sub_lci:
            if k.termination is None:
                '''
                # this is necessary because unobserved_exchanges() returns ExchangeValues for some reason (instead 
                of ExchangeRefs) and they detect and ignore NullContext terminations for some reason, causing 
                null-capped exchanges to show up here as cutoffs.  That may be desirable, actually. maybe we should
                just leave it.  not for now, though.
                '''
                continue
            val = k.value * node_weight
            lci[k.flow, k.direction, k.termination] += val

    output = []
    for k, v in lci.items():
        flow, dirn, term = k
        output.append(ExchangeRef(parent, flow, dirn, value=v, termination=term))

    return sorted(output, key=lambda x: (x.direction == 'Input', x.value), reverse=True)
