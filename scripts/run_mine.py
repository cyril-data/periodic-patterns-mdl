from classPatterns import PatternCollection, Pattern, DataSequence, computePeriodDiffs, computePeriod, cost_triple, cost_one, computeLengthCycle, Candidate, CandidatePool, sortPids
from extractCycles import compute_cycles_dyn, extract_cycles_fold
from readData import readSequence, readSequenceSacha, readEventsDict, group_syms
import pdb
import numpy
import re
import sys
import datetime
import itertools
import os
import glob
import pickle
import argparse

numpy.set_printoptions(suppress=True)

# EXAMPLE RUN
# python run_mine.py sacha_test --print-text --events_file "../data/SachaTrackSTMP/org/event_codes_out.txt" -U minutes -T "2018-04-02 10:10:00" -F "%Y-%m-%d %H:%M:%S" -D shift tX event eventTxt

OFFSETS_T = [0, 1, -1]
MINE_CPLX = True
TOP_KEACH = 5
USE_GRIDS = False  # True
CHECK_HORDER = True

PICKLE = 0  # 1 -> load pickled init cands; -1 -> store pickled init cands; 0 -> nothing


BASIS_REP = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DATA_REP = BASIS_REP+"/data/"
XPS_REP = BASIS_REP+"/xps/runs/"

series_params = {}
series_params["bugzilla_0_rel_all"] = {"input_file": "traces/trace_bugzilla_0_data.dat", "timestamp": False}
series_params["bugzilla_1_rel_all"] = {"input_file": "traces/trace_bugzilla_1_data.dat", "timestamp": False}
series_params["3zap_0_rel"] = {"input_file": "traces/trace_kptrace_3zap_0_data.dat", "timestamp": False}
series_params["3zap_1_rel"] = {"input_file": "traces/trace_kptrace_3zap_1_data.dat", "timestamp": False}

# series_params["samba_auth_abs"] = {"input_file": "samba_commits/commit_auth_data.dat", "timestamp": True}
series_params["samba_auth_abs"] = {"input_file": "samba_commits/commit_auth_data_smll.dat", "timestamp": True}

for grain in [1, 15, 30, 60, 720, 1440]:
    series_params["sacha_18_absI_G%d" % grain] = {"input_file": "sacha/data_18-03-22_lagg200NL.txt", "timestamp": True,
                                                  "granularity": grain, "I": True}

series_params["sacha_18_rel"] = {"input_file": "sacha/data_18-03-22_lagg200NL.txt", "timestamp": False}
# series_params["sacha_18_rel_2000"] = {"input_file": "sacha/data_18-03-22_lagg200NL.txt",
#                                  "timestamp": False, "drop_event_codes":[0, 126, 33]}
# series_params["sacha_18_abs_2000W"] = {"input_file": "sacha/data_18-03-22_lagg200NL.txt",
#                                  "timestamp": True, "max_len": 2000, "max_p": 7*24*60}

series_params["sacha_test"] = {"input_file": "sacha/data_18-03-22_lagg200NL.txt", "timestamp": True,
                               "granularity": 10, "I": True, "events": ["1010_I", "207_E", "207_S"]}  # "drop_event_codes": [0, 126, 33], "max_len": 200}

for f in glob.glob(DATA_REP+"UbiqLog/prepared/*_data.dat"):
    bb = f.split("/")[-1].strip("_data.dat")
    if not re.search("ISE", bb):
        series_params["UbiqLog_%s_rel" % bb] = {"filename": f, "timestamp": False}
    else:
        series_params["UbiqLog_%s_abs" % bb] = {"filename": f, "timestamp": True}

series_groups = ["ALL", "OTHER", "UBIQ_ABS", "UBIQ_REL", "TEST", "SACHA"]


def log_write(fo_log, what):
    if fo_log is not None:
        fo_log.write(what)


def bronKerbosch3Plus(graph, collect, P, R=set(), X=set()):
    if len(P) == 0 and len(X) == 0:
        if len(R) > 2:
            collect.append(R)
    else:
        lP = list(P)
        for v in lP:
            bronKerbosch3Plus(graph, collect, P.intersection(graph[v]), R.union([v]), X.intersection(graph[v]))
            P.remove(v)
            X.add(v)


# PREPARE PATTERNS
########################################################
def prepare_pattern_simple(occs, alpha, p0=None, r0=None):
    if r0 is None:
        r0 = len(occs)
    if p0 is None:
        p0 = computePeriod(occs)
    tree = {0: {"p": p0, "r": r0, "children": [(1, 0)], "parent": None},
            1: {"event": alpha, "parent": 0}}
    E = [(occs[i]-occs[i-1])-p0 for i in range(1, len(occs))]
    p = Pattern(tree)
    return (p, occs[0], E)


def prepare_candidate_two_nested(P_minor, p0, r0, p1, r1, first_rs):
    if (p0 <= 0) or (r0 <= 0) or (p1 <= 0) or (r1 <= 0):
        pdb.set_trace()
    tree = {0: {"p": p0, "r": r0, "children": [(1, 0)], "parent": None},
            1: {"p": p1, "r": r1, "children": [(2, 0)], "parent": 0}}

    if P_minor[0].isComplex():
        nodes, offset, nmap = P_minor[0].getTranslatedPNodes(1)
        ch = nodes.pop(nmap[0])["children"]
        for c in ch:
            nodes[c[0]]["parent"] = 1
        tree[1]["children"] = ch
        tree.update(nodes)
    else:
        tree[2] = {"event": P_minor[0].getEvent(), "parent": 1}

    Pblks_occs = []
    Pblks_errs = []
    for ci, cand in enumerate(P_minor):
        Pblks_occs.append(cand.getBlocksO(first_rs[ci]))
        Pblks_errs.append(cand.getBlocksE(first_rs[ci]))

    O = []
    E = []
    for i in range(r0):
        for j in range(r1):
            if j == 0:
                if i > 0:
                    E.append((Pblks_occs[i][j][0]-Pblks_occs[i-1][j][0])-p0)
            else:
                E.append((Pblks_occs[i][j][0]-Pblks_occs[i][j-1][0])-p1)
            E.extend(Pblks_errs[i][j])
            O.extend(Pblks_occs[i][j])
    p = Pattern(tree)
    return Candidate(-1, p, O, E)


def prepare_tree_nested(cand, prds, lens):
    P = cand.getPattern()
    if P is None:
        depth = 1
    else:
        depth = len(P.getCyclePs())

    tree = {}
    for i in range(len(prds)-depth+1):
        tree[i] = {"p": prds[i], "r": lens[i], "children": [(i+1, 0)], "parent": i-1}
    tree[0]["parent"] = None

    if P is None:
        tree[i+1] = {"event": cand.getEvent(), "parent": i}
    else:
        nodes, offset, nmap = cand.getTranslatedPNodes(i)
        ch = nodes.pop(nmap[0])["children"]
        for c in ch:
            nodes[c[0]]["parent"] = i
        tree[i]["children"] = ch
        tree.update(nodes)
    return tree


def prepare_candidate_nested(cp_det, P_minor, cmplx_candidates):

    idxs = cp_det[-1]
    pr_key = cp_det[1]
    tmp = pr_key.split("_")
    prds = list(map(int, tmp[0].split("+")))
    lens = list(map(int, tmp[1].split("*")))[::-1]

    occs = []
    for idx in idxs:
        occs.extend(cmplx_candidates[idx].getOccs())

    if cmplx_candidates[idxs[0]].getPattern() is None:
        depth = 1
    else:
        depth = len(cmplx_candidates[idxs[0]].getPattern().getCyclePs())

    list_reps = list(itertools.product(*[range(l) for l in lens[:-depth]]))
    map_reps = dict([(v, k) for (k, v) in enumerate(list_reps)])
    t00, Es = (None, [])
    for pi, pp in enumerate(list_reps):
        t0i = cmplx_candidates[idxs[pi]].getT0()
        Ei = cmplx_candidates[idxs[pi]].getE()
        if pi == 0:
            t00 = t0i
        else:
            copy_pp = list(pp)
            i = len(pp)-1
            while pp[i] == 0:
                i -= 1
            copy_pp[i] -= 1
            t0prec = cmplx_candidates[idxs[map_reps[tuple(copy_pp)]]].getT0()
            Es.append((t0i - t0prec) - prds[i])
        Es.extend(Ei)
    tree = prepare_tree_nested(cmplx_candidates[idxs[0]], prds, lens)
    p = Pattern(tree)
    return Candidate(-1, p, occs, Es)


def prepare_candidate_concats(cands, p0, r0, first_rs):
    if (p0 <= 0) or (r0 <= 0):
        pdb.set_trace()

    tree = {0: {"p": p0, "r": r0, "children": [], "parent": None}}
    offset = 0
    Pblks_occs = []
    Pblks_errs = []
    for ci, cand in enumerate(cands):

        Pblks_occs.append(cand.getBlocksO(first_rs[ci]))
        Pblks_errs.append(cand.getBlocksE(first_rs[ci]))

        nodes, offset, nmap = cand.getTranslatedPNodes(offset)
        offset -= 1
        ch = nodes.pop(nmap[0])["children"]
        if ci > 0:
            ch[0] = (ch[0][0], Pblks_occs[ci][0][0]-Pblks_occs[ci-1][0][0])
        tree[0]["children"].extend(ch)
        for c in ch:
            nodes[c[0]]["parent"] = 0
        tree.update(nodes)

    ds = [c[1] for c in tree[0]["children"]]
    O = []
    E = []
    t00 = None
    for ri in range(r0):
        for ei in range(len(Pblks_occs)):
            O.extend(Pblks_occs[ei][ri])
            if ei == 0:
                if ri == 0:
                    t00 = Pblks_occs[ei][ri][0]
                else:
                    E.append((Pblks_occs[ei][ri][0] - Pblks_occs[ei][ri-1][0])-p0)
            else:
                E.append((Pblks_occs[ei][ri][0] - Pblks_occs[ei-1][ri][0])-ds[ei])
            E.extend(Pblks_errs[ei][ri])
    p = Pattern(tree)
    return Candidate(-1, p, O, E)

# MINE INITIAL CANDIDATES
########################################################


def mine_cycles_alpha(occs, alpha, data_details, costOne, fo_log=None, max_p=None):
    return extract_cycles_alpha(occs, alpha, data_details, costOne, fo_log, max_p)


def extract_cycles_alpha(occs, alpha, data_details, costOne, fo_log=None, max_p=None):
    ## XX = [3-2*k+numpy.log2(k-1)-k*numpy.log2(data_details["nbOccs"][alpha])+(k-1)*numpy.log2(data_details["nbOccs"][-1])+(k-2)*numpy.log2(data_details["deltaT"]+1) for k in range(3, 10)]
    bound_dE = numpy.log2(data_details["deltaT"]+1) - 2
    log_write(fo_log, "Cycle extraction cost_one=%s bound_dE=%s\n" % (costOne, bound_dE))
    dyn_cycles = compute_cycles_dyn(occs, alpha, data_details, residuals=False)
    drop_occs = set()
    for dc in dyn_cycles:
        if len(dc["occs"]) > 10:
            drop_occs.update(dc["occs"][5:-5])
    if len(drop_occs) > 0:
        tmp_occs = sorted(set(occs).difference(drop_occs))
        log_write(fo_log, "Dropping from fold %d, left %d\n" % (len(drop_occs), len(tmp_occs)))
    else:
        tmp_occs = occs
    chains, triples_tmp = extract_cycles_fold(tmp_occs, alpha, data_details, bound_dE, costOne, costOne, max_p)
    triples = [{"alpha": alpha, "occs": [tmp_occs[tt] for tt in t[-1]], "p": computePeriod([tmp_occs[tt] for tt in t[-1]]), "cost": t[-2]} for t in triples_tmp]
    # for ti, t in enumerate(triples):
    #     cost_check = computeLengthCycle(data_details, t)
    #     if numpy.abs(cost_check-t["cost"]) > 1:
    #         pdb.set_trace()
    #         print(ti, t, cost_check)

    cycles = [Candidate(-1, c) for c in merge_cycle_lists([dyn_cycles, chains, triples])]
    # print("Cost 3 res:", 3*costOne)
    # cycles.sort(key=lambda c:c["cost"]/len(c["occs"]))
    # for c in cycles:
    #     src = c["source"]
    #     old_cst = c["cost"]
    #     costs_triples = [computeLengthCycle(data_details, {"p": None, "alpha": alpha, "occs": c["occs"][i:i+3]}) for i in range(len(c["occs"])-2)]
    #     nc = Candidate(-1, c)
    #     cst = nc.computeCost(data_details, force=True)
    #     pref = ""
    #     if nc.getCostRatio() > costOne:
    #         pref += "---"
    #     else:
    #         pref += "+++"
    #     if numpy.max(costs_triples) > 3*costOne:
    #         pref += "---"
    #     else:
    #         pref += "+++"
    #     print("%s\t%s vs. %s [%s]" % (pref, old_cst, nc, src[0])) #, costs_triples)
    selected_ids = filter_candidates_topKeach(cycles, k=TOP_KEACH)
    log_write(fo_log, "%d/%d merged cycles (%d dyn, %d chains, %d triples)\n" % (len(selected_ids), len(cycles), len(dyn_cycles), len(chains), len(triples)))
    return [cycles[s] for s in selected_ids]


def merge_cycle_lists(cyclesL):
    keys = []
    for ci, cycles in enumerate(cyclesL):
        # keys.extend([(":".join(map(str, kk["occs"])), ki, ci) for ki,kk in enumerate(cycles)])
        keys.extend([((kk["occs"][0], len(kk["occs"]), kk["p"]), ki, ci) for ki, kk in enumerate(cycles)])
    keys.sort()

    if len(keys) > 0:
        cycles = [cyclesL[keys[0][2]][keys[0][1]]]
        cycles[-1]["source"] = (keys[0][2], keys[0][1])

    for i in range(1, len(keys)):
        if keys[i][0] != keys[i-1][0]:
            cycles.append(cyclesL[keys[i][2]][keys[i][1]])
            cycles[-1]["source"] = (keys[i][2], keys[i][1])
        else:
            if cyclesL[keys[i][2]][keys[i][1]]["cost"] < cycles[-1]["cost"]:
                cycles[-1] = cyclesL[keys[i][2]][keys[i][1]]
                cycles[-1]["source"] = (keys[i][2], keys[i][1])
    return cycles


# COMBINE CANDIDATES VERTICALLY
########################################################
def run_combine_vertical(cpool, data_details, dcosts, nkey="H", fo_log=None):
    minorKeys = cpool.getNewMinorKeys(nkey)
    candidates = []
    for mk in minorKeys:
        if len(cpool.getCidsForMinorK(mk)) >= 3:
            if USE_GRIDS and (mk in data_details["nbOccs"]):  # only for simple events
                candidates.extend(run_combine_vertical_event(cpool, mk, data_details, fo_log))
            else:
                candidates.extend(run_combine_vertical_cands(cpool, mk, data_details, fo_log))

    if len(candidates) > 0:
        selected_ids = filter_candidates_topKeach(candidates, k=TOP_KEACH)
        log_write(fo_log, "%d/%d candidate vertical filtered (%s)\n" % (len(selected_ids), len(candidates), nkey))
        return [candidates[s] for s in selected_ids]
    return []


def run_combine_vertical_cands(cpool, mk, data_details, fo_log=None):
    cmplx_candidatesX = [cpool.getCandidate(cid) for cid in cpool.getCidsForMinorK(mk)]
    nested, covered = nest_cmplx(cmplx_candidatesX, mk, data_details)

    if len(nested) > 0:
        # selected = filter_candidates_cover(nested)
        selected_ids = filter_candidates_topKeach(nested, k=TOP_KEACH)
        log_write(fo_log, "%d/%d candidate vertical combinations selected (%s)\n" % (len(selected_ids), len(nested), mk))
        return [nested[s] for s in selected_ids]
    return []


def run_combine_vertical_event(cpool, mk, data_details, fo_log=None):
    store_candidates = find_complexes(cpool, mk, data_details)
    if len(store_candidates) == 0:
        return []

    cmplx_candidates = compute_costs_verticals(store_candidates, cpool, mk, data_details)
    log_write(fo_log, "%d cmplx selected" % (len(cmplx_candidates)))

    nested, covered = nest_cmplx(cmplx_candidates, mk, data_details)
    nested.extend([cmplx_cand for cci, cmplx_cand in enumerate(cmplx_candidates) if cci not in covered])

    # selected = filter_candidates_cover(nested)
    selected_ids = filter_candidates_topKeach(nested, k=TOP_KEACH)
    log_write(fo_log, "%d/%d candidate vertical combinations selected (grid %s)" % (len(selected_ids), len(nested), mk))
    return [nested[s] for s in selected_ids]


def get_top_p(occ_ordc):
    top1, top2, topN = (0, 1, -1)
    if top2+1 < len(occ_ordc) and occ_ordc[top2][0] == occ_ordc[top2+1][0]:
        topN = top2+1
        while topN+1 < len(occ_ordc) and occ_ordc[topN][0] == occ_ordc[topN+1][0]:
            topN += 1
        if numpy.abs(occ_ordc[top1][1] - occ_ordc[topN][1]) > numpy.abs(occ_ordc[top1][1] - occ_ordc[top2][1]):
            (top2, topN) = (topN, top2)
    return (top1, top2, topN)


def find_complexes(cpool, mk, data_details):
    occs_to_cycles = {}
    cids = cpool.getCidsForMinorK(mk)
    if len(cids) < 4:  # not enough to make combinations
        return []

    for cid in cids:
        for pid in cpool.getPidsForCid(cid):
            (t0i, p0, r0, offset, cumEi, _) = cpool.getProp(pid)
            remain = r0-offset
            if t0i not in occs_to_cycles:
                occs_to_cycles[t0i] = {}
            if p0 not in occs_to_cycles[t0i] or occs_to_cycles[t0i][p0][0] < remain:
                occs_to_cycles[t0i][p0] = (remain, cid)

    occs_to_ordc = {}
    top_two = {}
    for occ, dt in occs_to_cycles.items():
        if len(dt) > 1:
            ### triples (nb_occ_after, period, cycle_id)
            occs_to_ordc[occ] = sorted([(v[0], k, v[1]) for k, v in dt.items()], reverse=True)
            top_two[occ] = get_top_p(occs_to_ordc[occ])

    if len(occs_to_ordc) == 0:
        return []

    cids_keep = set(cids)
    soccs = sorted(occs_to_ordc.keys())
    map_soccs = dict([(v, k) for (k, v) in enumerate(soccs)])
    scores = numpy.array([occs_to_ordc[x][top_two[x][0]][0]*occs_to_ordc[x][top_two[x][1]][0] for x in soccs])
    store_candidates = []
    same_score_candidates = []
    cids_drop = set()

    # print("nb cycles DYN=%d FOLD=%d start_comb=%d" % (nb_dync, len(cycles)-nb_dync, len(start_comb_seq)))
    while numpy.max(scores) > 0:
        topi = numpy.argmax(scores)

        occ = soccs[topi]
        (nbOleftA, pA, ciA) = occs_to_ordc[occ][top_two[occ][0]]
        (nbOleftB, pB, ciB) = occs_to_ordc[occ][top_two[occ][1]]

        # retrieve the length of the cycles starting along the two sides
        if OFFSETS_T == [0]:  # strictly same period
            Ws = [occs_to_cycles.get(nocc, {}).get(pB, (0, -1)) for nocc in cpool.getCandidate(ciA).getMajorO()[-nbOleftA::]]
            Hs = [occs_to_cycles.get(nocc, {}).get(pA, (0, -1)) for nocc in cpool.getCandidate(ciB).getMajorO()[-nbOleftB::]]

        else:  # tolerate period +- offset
            Wcids, Wlefts, i = ([], [], 0)
            while i >= 0 and i < nbOleftA:
                nocc = cpool.getCandidate(ciA).getMajorO()[-nbOleftA+i]
                if nocc in occs_to_cycles:
                    ps = occs_to_cycles[nocc].keys()
                    ppi = numpy.argmin([numpy.abs(k-pB) for k in ps])
                    nleft, ncid = occs_to_cycles[nocc][ps[ppi]]
                    if ncid not in Wcids:
                        Wcids.append(ncid)
                        Wlefts.append(nleft)
                        i += 1
                    else:
                        i = -1
                else:
                    i = -1

            Hcids, Hlefts, i = ([], [], 0)
            while i >= 0 and i < nbOleftB:
                nocc = cpool.getCandidate(ciB).getMajorO()[-nbOleftB+i]
                if nocc in occs_to_cycles:
                    ps = occs_to_cycles[nocc].keys()
                    ppi = numpy.argmin([numpy.abs(k-pA) for k in ps])
                    nleft, ncid = occs_to_cycles[nocc][ps[ppi]]
                    if ncid not in Hcids:
                        Hcids.append(ncid)
                        Hlefts.append(nleft)
                        i += 1
                    else:
                        i = -1
                else:
                    i = -1

        h, w = (1, 1)
        if len(Hcids) > 2 and len(Wcids) > 2:
            # compute the actual size of tiles for different end corners
            Wsmin = numpy.array([numpy.min(Wlefts[:i+1]) for i in range(len(Wlefts))])
            Hsmin = numpy.array([numpy.min(Hlefts[:i+1]) for i in range(len(Hlefts))])
            I, J = numpy.mgrid[0:len(Hcids), 0:len(Wcids)]
            sizes = numpy.minimum(Wsmin[J], I+1) * numpy.minimum(Hsmin[I], J+1)
            # pick the end corner of the largest tile
            hi, wi = numpy.unravel_index(numpy.argmax(sizes + (I/(2.*I.shape[0])+J/(2.*J.shape[1]))), sizes.shape)
            # hh,ww = (hi+1, wi+1)
            h, w = (numpy.minimum(Wsmin[J], I+1)[hi, wi], numpy.minimum(Hsmin[I], J+1)[hi, wi])

        if h > 2 and w > 2:
            same_score_candidates.append({"cids": (Hcids[:h], Wcids[:w]),
                                          "lefts": (Hlefts[:h], Wlefts[:w]),
                                          "ps": (pA, pB),
                                          "corner": occ,
                                          "dims": (h, w)})

        if top_two[occ][-1] > -1:  # if there is another pair with same score
            direct = +1
            if top_two[occ][-1] < top_two[occ][1]:
                direct = -1
            if top_two[occ][-1] == top_two[occ][1]+direct:
                top_two[occ] = (top_two[occ][0], top_two[occ][1]+direct, -1)
            else:
                top_two[occ] = (top_two[occ][0], top_two[occ][1]+direct, top_two[occ][-1])

        else:

            scores[topi] = -1

            if len(same_score_candidates) > 0:
                same_score_candidates.sort(key=lambda x: (x["dims"][0]*x["dims"][1], x["ps"][1]), reverse=True)
                tscore = same_score_candidates[0]["dims"][0]*same_score_candidates[0]["dims"][1]

                for cand in same_score_candidates[:1]:
                    if cand["dims"][0]*cand["dims"][1] == tscore:
                        cids_drop.update(cand["cids"][0]+cand["cids"][1])
                        store_candidates.append(cand)

                same_score_candidates = []

        # update scores
        # strictest: remove all cycles involved
        ## cids_drop = Wcids + Hcids
        if len(cids_drop) > 0:
            cids_keep.difference_update(cids_drop)
            oids = set().union(*[cpool.getCandidate(cid).getMajorO() for cid in cids_drop])
            for oid in oids:
                if oid not in occs_to_ordc:
                    continue
                excl = [t for t in occs_to_ordc[oid] if t[-1] in cids_drop]
                occs_to_ordc[oid] = [t for t in occs_to_ordc[oid] if t[-1] not in cids_drop]
                if len(occs_to_ordc[oid]) > 1:
                    top_two[oid] = get_top_p(occs_to_ordc[oid])
                    scores[map_soccs[oid]] = occs_to_ordc[oid][top_two[oid][0]][0]*occs_to_ordc[oid][top_two[oid][1]][0]
                    for (nb_left, prd, cid) in excl:
                        del occs_to_cycles[oid][prd]
                else:
                    scores[map_soccs[oid]] = -1
            cids_drop = set()
    return store_candidates


def compute_costs_verticals(store_candidates, cpool, mk, data_details):
    selection = []
    store_candidates.sort(key=lambda x: x["dims"][0]*x["dims"][1], reverse=True)
    for ci, cand in enumerate(store_candidates):
        new_cands = {}
        sum_cost = {}
        sum_nboccs = {}

        for hw in [0, 1]:  # consider both ways of nesting
            Pdiffs_minor = []
            Poccs_major = []
            first_rs = []
            # occurrence list and periods
            P_minor = [cpool.getCandidate(cid) for cid in cand["cids"][hw]]
            for cci, P in enumerate(P_minor):
                first_rs.append(P.getMajorR()-cand["lefts"][hw][cci])
                tmp = P.getMajorO()[first_rs[-1]:first_rs[-1]+cand["dims"][1-hw]]
                Poccs_major.append(tmp[0])
                Pdiffs_minor.extend(numpy.diff(tmp))

            if mk in data_details["nbOccs"]:
                sum_cost[hw] = cost_one(data_details, mk)
                sum_nboccs[hw] = 1.
            else:
                sum_cost[hw] = numpy.sum([c.getCost() for c in P_minor])
                sum_nboccs[hw] = numpy.sum([c.getNbOccs() for c in P_minor])

            p1 = computePeriodDiffs(Pdiffs_minor)
            p0 = computePeriod(Poccs_major)
            r0, r1 = (cand["dims"][hw], cand["dims"][1-hw])
            new_cands[hw] = prepare_candidate_two_nested(P_minor, p0, r0, p1, r1, first_rs)
            new_cands[hw].computeCost(data_details)

        choose_id = 0
        # choose inside/outside
        if new_cands[1].getCostRatio() < new_cands[0].getCostRatio():
            choose_id = 1
        if new_cands[choose_id].getCostRatio() < (sum_cost[choose_id]/sum_nboccs[choose_id]):
            selection.append(new_cands[choose_id])
    return selection


def nest_cmplx(cmplx_candidates, P_minor, data_details):
    map_cmplx_pos = {}
    for cki, c in enumerate(cmplx_candidates):
        if c.getPattern() is not None:
            p_str = "+".join(["%d" % ppp for ppp in c.getPattern().getCyclePs()])
            r_str = "*".join(["%d" % ppp for ppp in c.getPattern().getCycleRs()[::-1]])
            pr_key = p_str+"_"+r_str
        else:
            pr_key = "%d_%d" % (c.getMajorP(), c.getMajorR())
        if pr_key not in map_cmplx_pos:
            map_cmplx_pos[pr_key] = []
        map_cmplx_pos[pr_key].append((c.getT0(), [cki]))

    keep = []
    while len(map_cmplx_pos) > 0:
        map_prev = map_cmplx_pos
        map_cmplx_pos = {}
        for pr_key, u_elems in map_prev.items():
            store = set(range(len(u_elems)))
            if len(u_elems) > 2:
                elems = sorted(u_elems)
                i = 1
                while i < len(elems):
                    if elems[i][0] == elems[i-1][0]:
                        sum_costsA = numpy.sum([cmplx_candidates[cci].getCost() for cci in elems[i][1]])
                        sum_costsB = numpy.sum([cmplx_candidates[cci].getCost() for cci in elems[i-1][1]])
                        if sum_costsA < sum_costsB:
                            elems.pop(i-1)
                        else:
                            elems.pop(i)
                    else:
                        i += 1
                cpkids = [e[1] for e in elems]
                t0s = [e[0] for e in elems]
                costSpare = cmplx_candidates[cpkids[0][0]].getCostNoE(data_details)
                bound_dE = numpy.log2(data_details["deltaT"]+1) - 2
                chains_x, triples_x = extract_cycles_fold(t0s, cmplx_candidates[cpkids[0][0]].getEventTuple(), data_details, bound_dE, -costSpare, -costSpare)
                for triple in triples_x:
                    pr_key_kid = "%d+%s*%d" % (triple[1], pr_key, len(triple[-1]))
                    if pr_key_kid not in map_cmplx_pos:
                        map_cmplx_pos[pr_key_kid] = []
                    comb_kids = []
                    for cc in triple[-1]:
                        comb_kids.extend(cpkids[cc])
                    map_cmplx_pos[pr_key_kid].append((t0s[triple[-1][0]], comb_kids))
                    store.difference_update(triple[-1])

                for chain in chains_x:
                    pM = computePeriod(chain["occs"])
                    pr_key_kid = "%d+%s*%d" % (pM, pr_key, len(chain["occs"]))
                    if pr_key_kid not in map_cmplx_pos:
                        map_cmplx_pos[pr_key_kid] = []
                    comb_kids = []
                    for cc in chain["pos"]:
                        comb_kids.extend(cpkids[cc])
                    map_cmplx_pos[pr_key_kid].append((chain["occs"][0], comb_kids))
                    store.difference_update(chain["pos"])

            for epp in store:
                if not type(u_elems[epp][1]) is int:
                    ### size, pr_key, t0, indices in cmplx_candidates
                    keep.append((eval(pr_key.split("_")[-1]), pr_key, u_elems[epp][0], u_elems[epp][1]))

    keep.sort()
    nested_patts = []
    covered = set()
    prev_size = -1
    while len(keep) > 0:
        next_cp = keep.pop()
        if len(set(next_cp[-1]).difference(covered)) > 2 or next_cp[0] == prev_size:
            prev_size = next_cp[0]
            new_cand = prepare_candidate_nested(next_cp, P_minor, cmplx_candidates)
            new_cand.computeCost(data_details)

            covered.update(next_cp[-1])
            nested_patts.append(new_cand)
    return nested_patts, covered


def getPidsSlice(patterns_props, pids, slice_size, col, max_v):
    if patterns_props[pids[-1], col] <= max_v:
        return pids
    elif patterns_props[pids[0], col] > max_v:
        return []
    ii = numpy.where(patterns_props[pids[::slice_size]+[pids[-1]], col] > max_v)[0]
    last_id = ((ii[0]-1)*slice_size)+numpy.where(patterns_props[pids[(ii[0]-1)*slice_size:ii[0]*slice_size+1], col] > max_v)[0][0]
    return pids[:last_id]


# COMBINE CANDIDATES HORIZONTALLY
########################################################
def run_combine_horizontal(cpool, data_details, dcosts, nkey="V", fo_log=None):
    if cpool.nbNewCandidates(nkey) == 0:
        return []

    pids = list(cpool.getSortedPids())
    patterns_props = cpool.getPropMat()

    pids_new = None
    Inew = patterns_props[pids, Candidate.prop_map["new"]] == cpool.getNewKNum(nkey)
    if numpy.sum(Inew) == 0:
        return []
    if numpy.sum(Inew) < 500:
        pids_new = [pids[p] for p in numpy.where(Inew)[0]]

    log_write(fo_log, "Horizontal org %d pids (%s)\n" % (len(pids), nkey))
    ## pids = [pid for pid in pids if (patterns_props[pid, Candidate.prop_map["offset"]] < 2)]

    keep_cands = {}
    drop_overlap = 0
    # for each pattern Pa in turn
    log_write(fo_log, "Horizontal %d pids (%s)\n" % (len(pids), nkey))
    while len(pids) > 1:
        if len(pids) % 1000 == 0:
            log_write(fo_log, "Horizontal %d pids left (%s)\n" % (len(pids), nkey))

        if pids_new is not None:
            if len(pids_new) > 0:
                j = 0
                while pids[j] != pids_new[0] and ((patterns_props[pids[j], Candidate.prop_map["t0i"]] + patterns_props[pids[j], Candidate.prop_map["p0"]]) < patterns_props[pids_new[0], Candidate.prop_map["t0i"]]):
                    j += 1
                if pids[j] == pids_new[0]:
                    pids_new.pop(0)
                    if len(pids_new) == 0:  # last new pids reached -> last round
                        pids = [pids[j]]
                        j = 0
                pids = pids[j:]

        i = pids.pop(0)
        if len(pids) == 0:
            continue
        # if patterns_props[i,0] == 0:
        #     # log_details = True
        #     print("i=", i, patterns_props[i,:])
        # else:
        # if patterns_props[i,0] > 0:
        #     pdb.set_trace()
        #     print("Done with t0=0")

        # find other patterns Pb such that:
        # (1) don"t come from the same candidate
        # (2) first occurrence of Pb appears before the second repetition of Pa
        # (3) pb-pa <= 2 (cum_E of Pb) / r(r-1) with r = min(ra, rb)

        # (2)
        next_it = patterns_props[i, Candidate.prop_map["t0i"]] + patterns_props[i, Candidate.prop_map["p0"]]
        i_new = patterns_props[i, Candidate.prop_map["new"]] == cpool.getNewKNum(nkey)
        cmp_ids = []
        if i_new:  # i is new, compare to both new and old
            cmp_ids = numpy.array(getPidsSlice(patterns_props, pids, 500, Candidate.prop_map["t0i"], next_it))
        else:  # i is old, only compare to new
            if pids_new is not None:
                ppp = numpy.array(pids_new)
                cmp_ids = ppp[patterns_props[ppp, Candidate.prop_map["t0i"]] <= next_it]
            else:
                ppp = numpy.array(getPidsSlice(patterns_props, pids, 500, Candidate.prop_map["t0i"], next_it))
                if len(ppp) > 0:
                    cmp_ids = ppp[patterns_props[ppp, Candidate.prop_map["new"]] == cpool.getNewKNum(nkey)]
        ###

        sel_ids = []
        if len(cmp_ids) > 0:
            # (1)
            sel_ids = cmp_ids[patterns_props[cmp_ids, Candidate.prop_map["cid"]] != patterns_props[i, Candidate.prop_map["cid"]]]

        if len(sel_ids) > 0:
            # (3)
            rmins = 1.*numpy.minimum(patterns_props[i, Candidate.prop_map["r0"]]-patterns_props[i, Candidate.prop_map["offset"]],
                                     patterns_props[sel_ids, Candidate.prop_map["r0"]]-patterns_props[sel_ids, Candidate.prop_map["offset"]])
            sel_ids = sel_ids[numpy.abs(patterns_props[sel_ids, Candidate.prop_map["p0"]] - patterns_props[i, Candidate.prop_map["p0"]]) <= 2.*patterns_props[sel_ids, Candidate.prop_map["cumEi"]]/(rmins*(rmins-1))]

        for j in sel_ids:
            cand_pids = (i, j)
            cand_cids = tuple([patterns_props[cci, Candidate.prop_map["cid"]] for cci in cand_pids])
            cands = [cpool.getCandidate(cci) for cci in cand_cids]
            if (cands[0].getEvent() == cands[1].getEvent()) and (patterns_props[i, Candidate.prop_map["t0i"]] == patterns_props[j, Candidate.prop_map["t0i"]]):
                continue
            if len(set(cands[0].getEvOccs()).intersection(cands[1].getEvOccs())) > 0:
                drop_overlap += 1
                continue

            r0 = numpy.min(patterns_props[cand_pids, Candidate.prop_map["r0"]]-patterns_props[cand_pids, Candidate.prop_map["offset"]])
            p0 = patterns_props[cand_pids[0], Candidate.prop_map["p0"]]
            new_cand = prepare_candidate_concats(cands, p0, r0, patterns_props[cand_pids, Candidate.prop_map["offset"]])
            new_cand.computeCost(data_details)
            if CHECK_HORDER and patterns_props[i, Candidate.prop_map["t0i"]] == patterns_props[j, Candidate.prop_map["t0i"]] and \
                    (numpy.abs(patterns_props[cand_pids[0], Candidate.prop_map["p0"]] - patterns_props[cand_pids[1], Candidate.prop_map["p0"]]) <= 2.*patterns_props[cand_pids[1], Candidate.prop_map["cumEi"]]/(r0*(r0-1))):  # Equivalent flipped (same starting point)

                new_candX = prepare_candidate_concats([cands[1], cands[0]], patterns_props[cand_pids[1], Candidate.prop_map["p0"]], r0, patterns_props[[cand_pids[1], cand_pids[0]], Candidate.prop_map["offset"]])
                new_candX.computeCost(data_details)

                if (new_candX.getCost() < new_cand.getCost()) or (new_cand.getCost() == new_candX.getCost() and new_candX.getEventTuple() < new_cand.getEventTuple()):
                    new_cand = new_candX
                    cand_pids = (cand_pids[1], cand_pids[0])

            sum_cost = numpy.sum([c.getCost() for c in cands])
            sum_nboccs = numpy.sum([c.getNbOccs() for c in cands])

            if new_cand.getCostRatio() < (sum_cost/sum_nboccs):
                cov = set().union(*[c.getEvOccs() for c in cands])
                residuals = cov.difference(new_cand.getEvOccs())
                cresiduals = numpy.sum([dcosts[o[1]] for o in residuals])
                # if nkey == "V1":
                #     print("------------------------")
                #     print("\n".join(["%s\n\t%s" % (c, c.getEvOccs()) for c in cands]))
                #     print("%s\n\t%s" % (new_cand, new_cand.getEvOccs()))
                #     print("%d+%d=%d vs. %d vs. %d" % (new_cand.getNbOccs(), len(residuals), new_cand.getNbOccs()+len(residuals), len(cov), sum_nboccs))
                #     print("------------------------")

                if (new_cand.getCost()+cresiduals)/(new_cand.getNbOccs()+len(residuals)) < (sum_cost/sum_nboccs):

                    keep_cands[cand_pids] = new_cand

                    # for cci in [0,1]:
                    #     print("\tP[%s,%s]: %f/%d=%f %s t0=%d\t%s" % (cand_cids[cci], cand_pids[cci], cands[cci].getCost(), cands[cci].getNbOccs(), cands[cci].getCostRatio(), cands[cci].getEvent(), cands[cci].getT0(), patterns_props[cand_pids[cci], :]))

                    for pp in numpy.where(patterns_props[i, Candidate.prop_map["cid"]] == patterns_props[pids, Candidate.prop_map["cid"]])[0][::-1]:
                        pids.pop(pp)
                    if pids_new is not None:
                        for pp in numpy.where(patterns_props[i, Candidate.prop_map["cid"]] == patterns_props[pids_new, Candidate.prop_map["cid"]])[0][::-1]:
                            pids_new.pop(pp)
                        if len(pids_new) == 0:
                            pids = []

    log_write(fo_log, "Dropped overlap %d (%s)\n" % (drop_overlap, nkey))
    nb_generated = len(keep_cands)
    # selected_ids = filter_cidpairs_topKeach(keep_cands, k=3)
    selected_ids = filter_candidates_topKeach(keep_cands, k=TOP_KEACH)
    log_write(fo_log, "Generated %d/%d candidates (%s)\n" % (len(selected_ids), nb_generated, nkey))
    keep_cands = dict([(k, keep_cands[k]) for k in selected_ids])
    graph_candidates = {}
    for cand_pids in selected_ids:
        for cci in [0, 1]:
            if cand_pids[cci] not in graph_candidates:
                graph_candidates[cand_pids[cci]] = set([cand_pids[1-cci]])
            else:
                graph_candidates[cand_pids[cci]].add(cand_pids[1-cci])

    # drop_pairs = set()
    collect = []
    bronKerbosch3Plus(graph_candidates, collect, set(graph_candidates.keys()))
    log_write(fo_log, "BronKerbosch collected %d (%s)\n" % (len(collect), nkey))
    for cand_pids_unsrt in collect:
        cand_pids = sorted(cand_pids_unsrt, key=lambda x: (patterns_props[x, Candidate.prop_map["t0i"]], cpool.getCandidate(patterns_props[x, Candidate.prop_map["cid"]]).getEventTuple()))
        new_cand = makeCandOnOrder(cand_pids, data_details, patterns_props, cpool)

        # cands = [cpool.getCandidate(patterns_props[cci, Candidate.prop_map["cid"]]) for cci in cand_pids]
        # r0 = numpy.min(patterns_props[cand_pids, Candidate.prop_map["r0"]]-patterns_props[cand_pids, Candidate.prop_map["offset"]])
        # p0 = patterns_props[cand_pids[0], Candidate.prop_map["p0"]]
        # new_cand = prepare_candidate_concats(cands, p0, r0, patterns_props[cand_pids, Candidate.prop_map["offset"]])
        # new_cand.computeCost(data_details)

        if CHECK_HORDER and len(set(patterns_props[cand_pids, Candidate.prop_map["t0i"]])) < len(cand_pids):
            ppids = [s for s in selected_ids if (s[0] in cand_pids_unsrt) and (s[1] in cand_pids_unsrt)]
            ord_c = dict([(s, 0) for s in cand_pids])
            for ppid in ppids:
                ord_c[ppid[0]] += 1
            cand_pidsX = sorted(ord_c.keys(), key=lambda x: -ord_c[x])
            if cand_pidsX != cand_pids:
                new_candX = makeCandOnOrder(cand_pidsX, data_details, patterns_props, cpool)
                # print("PREF PIDS\n\t%s\n\t%s" % (new_cand, new_candX))

                if (new_candX.getCost() < new_cand.getCost()):  # or (new_cand.getCost() == new_candX.getCost() and new_candX.getEventTuple() < new_cand.getEventTuple()):
                    # print("Replaced PREF", new_candX.getCost(), new_cand.getCost())
                    new_cand = new_candX
                    cand_pids = cand_pidsX

        if CHECK_HORDER:
            cand_pidsY = sortPids(patterns_props, cand_pids_unsrt)
            if cand_pidsY != cand_pids:
                new_candY = makeCandOnOrder(cand_pidsY, data_details, patterns_props, cpool)
                # print("SORT PIDS\n\t%s\n\t%s" % (new_cand, new_candY))
                if new_candY.getCost() < new_cand.getCost():
                    # print("Replaced SORT", new_candY.getCost(), new_cand.getCost())
                    new_cand = new_candY
                    cand_pids = cand_pidsY

        sum_cost = numpy.sum([c.getCost() for c in cands])
        sum_nboccs = numpy.sum([c.getNbOccs() for c in cands])

        if new_cand.getCostRatio() < (sum_cost/sum_nboccs):
            # print("Pc: %f/%d=%f %s t0=%d\tvs. %s" % (new_cand.getCost(), new_cand.getNbOccs(), new_cand.getCostRatio(), new_cand.P, new_cand.getT0(), sum_cost/sum_nboccs))
            keep_cands[tuple(cand_pids)] = new_cand
            # drop_pairs.update(itertools.combinations(cand_pids, 2))

    # for dp in drop_pairs:
    #     keep_cands.pop(dp, None)
    selected = list(keep_cands.values())
    substitute_factorized(selected, data_details, fo_log)
    log_write(fo_log, "%d/%d candidate horizontal combinations selected (%s)\n" % (len(selected), nb_generated, nkey))
    return selected


def makeCandOnOrder(cand_pids, data_details, patterns_props, cpool):
    cands = [cpool.getCandidate(patterns_props[cci, Candidate.prop_map["cid"]]) for cci in cand_pids]
    r0 = numpy.min(patterns_props[cand_pids, Candidate.prop_map["r0"]]-patterns_props[cand_pids, Candidate.prop_map["offset"]])
    p0 = patterns_props[cand_pids[0], Candidate.prop_map["p0"]]
    new_cand = prepare_candidate_concats(cands, p0, r0, patterns_props[cand_pids, Candidate.prop_map["offset"]])
    new_cand.computeCost(data_details)
    return new_cand


# CANDIDATE SELECTION BASED ON COST/COV
########################################################
def filter_candidates_cover_slow(cands, dcosts, min_cov=1, adjust_occs=False, cis=None):
    if cis is None:
        if type(cands) is dict:
            cis = list(cands.keys())
        else:
            cis = list(range(len(cands)))

    for ci in cis:
        cands[ci].initUncovered()

    cis.sort(key=lambda x: cands[x].getCostUncoveredRatio())
    selected = []
    covered = set()
    max_eff = numpy.max(list(dcosts.values()))
    while len(cis) > 0:
        nxti = cis.pop(0)
        if cands[nxti].getCostUncoveredRatio() <= max_eff:
            nb = cands[nxti].updateUncovered(covered)
            if (nb >= min_cov) and cands[nxti].isEfficient(dcosts):
                i = 0
                while (i < len(cis)) and (cands[nxti].getCostUncoveredRatio() > cands[cis[i]].getCostUncoveredRatio()):
                    i += 1
                if i == 0:
                    if not cands[nxti].isPattern() and adjust_occs:
                        cands[nxti].adjustOccs()
                    selected.append(nxti)
                    covered.update(cands[nxti].getUncovered())
                else:
                    cis.insert(i, nxti)
        else:
            cis = []
    return selected


def filter_candidates_cover(cands, dcosts, min_cov=1, adjust_occs=False, cis=None):
    if cis is None:
        if type(cands) is dict:
            cis = list(cands.keys())
        else:
            cis = list(range(len(cands)))

    for ci in cis:
        cands[ci].initUncovered()

    selected = []
    covered = set()
    if len(dcosts) == 0:
        return selected
    cis.sort(key=lambda x: cands[x].getCostUncoveredRatio())
    max_eff = numpy.min(list(dcosts.values()))
    while len(cis) > 0:
        nxti = cis.pop(0)
        if cands[nxti].getCostUncoveredRatio() <= max_eff:
            if cands[nxti].getNbUncovered() >= min_cov and cands[nxti].isEfficient(dcosts):

                if not cands[nxti].isPattern() and adjust_occs:
                    cands[nxti].adjustOccs()

                selected.append(nxti)
                covered.update(cands[nxti].getUncovered())

                if cands[nxti].getNbUncovered() > 0:
                    i = 0
                    while i < len(cis):
                        if cands[cis[i]].updateUncovered(cands[nxti].getUncovered()) < min_cov:
                            cis.pop(i)
                        elif (max_eff >= 0) and (cands[cis[i]].getCostUncoveredRatio() > max_eff):
                            cis.pop(i)
                        else:
                            i += 1
                    cis.sort(key=lambda x: cands[x].getCostUncoveredRatio())
        else:
            cids = []
    return selected


def filter_candidates_topKeach(cands, k=2):
    counts_cover = {}

    if type(cands) is dict:
        cis = list(cands.keys())
    else:
        cis = list(range(len(cands)))
    if len(cis) <= k:
        return cis

    cis.sort(key=lambda x: (cands[x].getCostRatio(), x))
    selected = []
    while len(cis) > 0:
        nxti = cis.pop(0)

        if cands[nxti].satisfiesMaxCountCover(counts_cover, k):
            cands[nxti].updateCountCover(counts_cover)
            selected.append(nxti)
    return selected


def filter_cidpairs_topKeach(cands, k=2):
    counts_cover = {}

    if type(cands) is dict:
        cis = list(cands.keys())
    else:
        cis = list(range(len(cands)))
    cis.sort(key=lambda x: cands[x].getCostRatio())
    selected = []
    while len(cis) > 0:
        nxti = cis.pop(0)
        ccc = [counts_cover.get(pp, 0) for pp in nxti]
        if numpy.min(ccc) <= k:
            #print("%s:\t%s\t%s\t->keep" % (nxti, cands[nxti], ccc))
            for pp in nxti:
                counts_cover[pp] = counts_cover.get(pp, 0)+1
            selected.append(nxti)
        # else:
        #     print("%s:\t%s\t%s\t->drop" % (nxti, cands[nxti], ccc))

    return selected


def substitute_factorized(cands, data_details, fo_log=None):
    for i in range(len(cands)):
        ext = cands[i].factorizePattern()
        if len(ext) > 0:
            ii = numpy.argmin([cands[i].getCost()]+[e.computeCost(data_details) for e in ext])
            if ii > 0:
                log_write(fo_log, "%s --> FACT\n" % cands[i])
                log_write(fo_log, "%s <-- FACT\n" % ext[ii-1])
                cands[i] = ext[ii-1]


def disp_seqs(seqs, ffo_log=None):
    if ffo_log is None:
        fo_log = sys.stdout
    else:
        fo_log = ffo_log

    ds = DataSequence(seqs)
    log_write(fo_log, ds.getInfoStr()+"\n")


def mine_seqs(seqs, fn_basis="-", max_p=None, writePCout_fun=None, out_fmt={}):
    if writePCout_fun is None:
        writePCout_fun = writePCout
    if fn_basis is None:
        fo_log = None
    elif fn_basis == "-":
        fo_log = sys.stdout
    else:
        fo_log = open(fn_basis+"_log.txt", "w")

    if type(seqs) is DataSequence:
        ds = seqs
    else:
        ds = DataSequence(seqs)
    log_write(fo_log, ds.getInfoStr()+"\n")

    data_details = ds.getDetails()
    dcosts = dict([(alpha, cost_one(data_details, alpha)) for alpha in data_details["nbOccs"].keys() if alpha != -1])

    tic = datetime.datetime.now()
    dT_sel = datetime.timedelta()
    tic_ev = tic
    log_write(fo_log, "[TIME] Start --- %s\n" % tic)
    cpool = CandidatePool()
    if PICKLE == 1 and fn_basis is not None:
        evs = []
    else:
        evs = ds.getEvents()
    for alpha, ev in enumerate(evs):

        tic_ev = datetime.datetime.now()
        seq = ds.getSequence(alpha)

        log_write(fo_log, "------------\n")
        log_write(fo_log, "SEQUENCE %s[%s]: (%d)\n" % (ev, alpha, len(seq)))

        cycles_alpha = mine_cycles_alpha(seq, alpha, data_details, dcosts[alpha], fo_log, max_p=max_p)
        cpool.addCands(cycles_alpha, costOne=dcosts[alpha])
        tac_ev = datetime.datetime.now()
        log_write(fo_log, "[TIME] Cycle extraction event %s done in %s\n" % (ev, tac_ev-tic_ev))
        tic_ev = tac_ev

    if PICKLE == -1 and fn_basis is not None and fn_basis != "-":
        fpick = "%s_init.pick" % re.sub("_log.txt", "", fo_log.name)
        fp = open(fpick, "w")
        pickle.dump(cpool, fp)
        fp.close()
        log_write(fo_log, "[PICKLE] Stored candidates to %s\n" % fpick)
    if PICKLE == 1 and fn_basis is not None and fn_basis != "-":
        fpick = "%s_init.pick" % re.sub("_log.txt", "", fo_log.name)
        pkl_file = open(fpick, "rb")
        cpool = pickle.load(pkl_file)
        pkl_file.close()
        log_write(fo_log, "[PICKLE] Loaded candidates from %s\n" % fpick)

    tac_init = datetime.datetime.now()
    log_write(fo_log, "[TIME] simple cycle mining done in %s\n" % (tac_init-tic))

    #############
    tic_sel = datetime.datetime.now()
    cdict = cpool.getCandidates()
    simple_cids = list(cdict.keys())
    log_write(fo_log, "[INTER] Simple selection (%d candidates) at %s\n" % (len(cdict), tic_sel))
    selected = filter_candidates_cover(cdict, dcosts, min_cov=3, adjust_occs=True)
    pc = PatternCollection([cdict[c].getPattT0E() for c in selected])
    writePCout_fun(pc, ds, fn_basis, "-simple", fo_log, out_fmt)
    tac_sel = datetime.datetime.now()
    dT_sel += (tac_sel - tic_sel)
    log_write(fo_log, "[INTER] Simple selection done in %s at %s\n" % ((tac_sel - tic_sel), tac_sel))
    #############

    log_write(fo_log, "------------------------\n")
    nkeyV, nkeyH = (None, None)
    roundi = 0
    while MINE_CPLX and cpool.nbNewCandidates() > 0:
        roundi += 1

        tic_round = datetime.datetime.now()
        candsV = run_combine_vertical(cpool, data_details, dcosts, nkeyH, fo_log)
        tac_rV = datetime.datetime.now()
        candsH = run_combine_horizontal(cpool, data_details, dcosts, nkeyV, fo_log)
        tac_rH = datetime.datetime.now()

        nkeyV, nkeyH = ("V%d" % roundi, "H%d" % roundi)
        log_write(fo_log, "-- %d Cands vertical (%s)\n" % (len(candsV), nkeyV))
        log_write(fo_log, "-- %d Cands horizontal (%s)\n" % (len(candsH), nkeyH))

        cpool.resetNew()
        cpool.addCands(candsV, nkeyV)
        cpool.addCands(candsH, nkeyH)
        tac_round = datetime.datetime.now()
        log_write(fo_log, "[TIME] Combination round %d done in %s (V=%s, H=%s, C=%s)\n" % (roundi, tac_round-tic_round, tac_rV-tic_round, tac_rH-tac_rV, tac_round-tac_rH))
        if roundi == 1:
            #############
            for (side, nks) in [("V", [nkeyV]), ("H", [nkeyH]), ("V+H", [nkeyV, nkeyH])]:
                tic_sel = datetime.datetime.now()
                cdict = cpool.getCandidates()
                to_filter = list(simple_cids)
                for nk in nks:
                    to_filter.extend(cpool.getNewCids(nk))
                log_write(fo_log, "[INTER] Simple+%s selection (%d candidates) at %s\n" % (side, len(to_filter), tic_sel))
                selected = filter_candidates_cover(cdict, dcosts, min_cov=3, adjust_occs=True, cis=to_filter)
                pc = PatternCollection([cdict[c].getPattT0E() for c in selected])
                writePCout_fun(pc, ds, fn_basis, "-simple+%s" % side, fo_log, out_fmt)
                tac_sel = datetime.datetime.now()
                dT_sel += (tac_sel - tic_sel)
                log_write(fo_log, "[INTER] Simple+%s selection done in %s at %s\n" % (side, (tac_sel - tic_sel), tac_sel))
        #############

    tac_comb = datetime.datetime.now()
    log_write(fo_log, "[TIME] Combinations done in %s\n" % (tac_comb-tac_init))

    #############
    cdict = cpool.getCandidates()
    log_write(fo_log, "Final selection (%d candidates) at %s\n" % (len(cdict), tac_comb))
    selected = filter_candidates_cover(cdict, dcosts, min_cov=3, adjust_occs=True)
    pc = PatternCollection([cdict[c].getPattT0E() for c in selected])
    writePCout_fun(pc, ds, fn_basis, "", fo_log, out_fmt)
    tac = datetime.datetime.now()
    log_write(fo_log, "[TIME] Final selection done in %s at %s\n" % (tac-tac_comb, tac))
    #############
    log_write(fo_log, "[TIME] Mining done in %s (-inter=%s)\n" % (tac-tic, (tac-tic)-dT_sel))
    log_write(fo_log, "[TIME] End --- %s\n" % tac)


def writePCout(pc, ds, fn_basis, suff, fo_log=None, out_fmt={}):
    if fn_basis is None:
        return
    if fn_basis == "-":
        fo_patts = sys.stdout
    else:
        fo_patts = open(fn_basis+("_patts%s.txt" % suff), "w")
    str_stats, str_pl = pc.strDetailed(ds, out_fmt)
    fo_patts.write(str_stats+str_pl)
    if fn_basis != "-":
        if fo_log is not None:
            log_write(fo_log, str_stats)
        fo_patts.close()


########################################################
########################################################
if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Periodic pattern miner")
    series_options_str = " among " + ", ".join(series_groups) + " and " + ", ".join(series_params.keys())
    parser.add_argument("series", type=str, nargs="*", help="series of experiments to replicate," + series_options_str, default=argparse.SUPPRESS)

    # mining
    parser.add_argument("-p", "--max_p", type=int, help="maximum period to consider", default=argparse.SUPPRESS)
    parser.add_argument("--display", action="store_true", help="just load and display the data, do not mine", default=argparse.SUPPRESS)

    # input
    parser.add_argument("--input_folder", type=str, help="folder containing the input data", default=argparse.SUPPRESS)
    parser.add_argument("-i", "--input_file", type=str, help="file containing the input data", default=argparse.SUPPRESS)
    parser.add_argument("-e", "--event", type=str, dest="events", action="append", help="regex pattern to filter and group events, patterns involving all of '%s' will be used to group events, else to filter them" % group_syms, default=argparse.SUPPRESS)
    parser.add_argument("-s", "--separator", type=str, dest="SEP", help="field separator used in the input file", default=argparse.SUPPRESS)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--absolute", action="store_true", dest="timestamp", help="event occurrences come with integer timestamps, i.e. use an absolute time reference", default=argparse.SUPPRESS)
    group.add_argument("--relative", action="store_false", dest="timestamp", help="event occurrences are not timestamped, i.e. no time reference only relative position", default=argparse.SUPPRESS)
    group.add_argument("--timestamps", action="store_true", dest="timestamp", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    group.add_argument("--no-timestamps", action="store_false", dest="timestamp", help=argparse.SUPPRESS, default=argparse.SUPPRESS)

    parser.add_argument("--min_len", type=int, help="events with fewer occurrences will be discarded", default=argparse.SUPPRESS)
    parser.add_argument("--max_len", type=int, help="events with more occurrences will be discarded", default=argparse.SUPPRESS)

    # sacha format
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-I", "--instant", action="store_true", dest="I", help="Use suffix I for instantaneous events, instead of S--E pair (sacha only)", default=argparse.SUPPRESS)
    # group.add_argument("--instant", action="store_true", dest="I", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    group.add_argument("--no-instant", action="store_false", dest="I", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    parser.add_argument("-G", "--granularity", type=int, help="Time granularity, used as divisor for the original times (sacha only)", default=argparse.SUPPRESS)
    parser.add_argument("-E", "--drop-event", type=str, dest="drop_event_codes", action="append", help="Filter events using hierachical codes, events of the corresponding types and sub-types will be dropped", default=argparse.SUPPRESS)

    parser.add_argument("--events_file", type=str, help="file containing the full text names of events", default=argparse.SUPPRESS)
    parser.add_argument("--events_sep", type=str, help="field separator used in the events file", default=argparse.SUPPRESS)

    # printing options
    parser.add_argument("--print-simple", dest="print_simple", action='store_true', help="print all found patterns, including simple cycles", default=argparse.SUPPRESS)
    parser.add_argument("--no-print-simple", dest="print_simple", action='store_false', help="print only complex cycles", default=argparse.SUPPRESS)
    parser.add_argument("--print-type", dest="print_type", action='store_true', help="print type of pattern", default=argparse.SUPPRESS)
    parser.add_argument("--no-print-type", dest="print_type", action='store_false', help="do not print type of pattern", default=argparse.SUPPRESS)
    parser.add_argument("--print-text", dest="print_text", action='store_true', help="print pattern tree with formatted times and events", default=argparse.SUPPRESS)
    parser.add_argument("--no-print-text", dest="print_text", action='store_false', help="do not print pattern tree with formatted times and events", default=argparse.SUPPRESS)

    pieces_c, pieces_h = Pattern.getPiecesHelp()
    ss = ", ".join(["%s (%s)" % (v, pieces_h[k]) for k, v in enumerate(pieces_c)])
    parser.add_argument('-D', "--print-details", choices=pieces_c, action="extend", nargs="*", type=str, default=[], help="Details of occurrences to print. Possible choices are: "+ss)
    parser.add_argument("-T", "--org-timestamp", type=str, help="Timestamp for t0", default=argparse.SUPPRESS)
    parser.add_argument("-F", "--fmt-timestamp", type=str, help="Format for timestamps, default \"%%Y-%%m-%%d %%H:%%M:%%S\"", default="%Y-%m-%d %H:%M:%S")
    parser.add_argument("-U", "--time-unit", type=str, help="Time unit, e.g. \"seconds\", \"minutes\", \"hours\" or \"days\"", default="seconds")

    # output
    parser.add_argument("-x", "--output_folder", type=str, help="Folder in which to save the results and logs", default=argparse.SUPPRESS)
    parser.add_argument("-o", "--output_basename", type=str, help="Basenames for the files in which to save the results and logs", default=argparse.SUPPRESS)
    parser.add_argument("--run_id", type=str, help="run identifier", default=argparse.SUPPRESS)

    pargs = vars(parser.parse_args())

    lseries = []
    groupped = ""
    if len(pargs.get("series", [])) > 0:
        lseries = pargs["series"]
        if lseries[0] not in series_params and lseries[0] not in ["ALL", "OTHER", "UBIQ_ABS", "UBIQ_REL", "TEST", "SACHA"] and "run_id" not in pargs:
            pargs["run_id"] = lseries.pop(0)
        if len(lseries) > 0 and lseries[-1] == "ALL":
            lseries = series_params.keys()
        if len(lseries) > 0 and lseries[-1] == "OTHER":
            lseries = [s for s in series_params.keys() if not (re.match("UbiqLog", s) or re.match("sacha_", s))]
        if len(lseries) > 0 and re.match("UBIQ_ABS", lseries[-1]):
            groupped = lseries[-1]
            lseries = [s for s in series_params.keys() if re.match("UbiqLog_.*_abs", s)]
        if len(lseries) > 0 and re.match("UBIQ_REL", lseries[-1]):
            groupped = lseries[-1]
            lseries = [s for s in series_params.keys() if re.match("UbiqLog_.*_rel", s)]
        if len(lseries) > 0 and re.match("SACHA", lseries[-1]):
            groupped = lseries[-1]
            lseries = [s for s in series_params.keys() if re.match("sacha_", s)]
    elif pargs.get("input_file") is not None:
        lseries = [None]

    run_id = pargs.get("run_id", "")
    if run_id == "_":
        run_id = datetime.datetime.now().strftime("%y%m%d%H%M%S")
    if len(run_id) > 0:
        print("RUN_ID: %s" % run_id)
        if not re.match("_", run_id):
            run_id = "_" + run_id

    for series in lseries:
        if series is None or series in series_params:
            params = dict(pargs)
            if series is not None:
                # COMMAND LINE PARAMS OVERRIDE SERIES DEFAULT, NOT THE OTHER WAY AROUND
                sp = dict(series_params[series])
                sp.update(params)
                params = sp
                input_name = series
                xps_rep = params.get("output_folder", XPS_REP)
                if "filename" not in params:
                    params["filename"] = params.get("input_folder", DATA_REP)+params.get("input_file")
                if "output_basename" in params:
                    basename = params["output_basename"] + "_" + series
                else:
                    basename = series

            else:
                input_name = params.get("input_file")
                xps_rep = params.get("output_folder", "")
                params["filename"] = params.get("input_folder", "")+params.get("input_file")
                basename = params.get("output_basename", "xps")

            if (series is not None and re.match("sacha", series)) or re.search("[^a-zA-Z0-9]sacha[^a-zA-Z0-9]", "_"+params["filename"]+"_"):
                seqs = readSequenceSacha(params)
            else:
                seqs = readSequence(params)

            if "events_file" in params:
                # TODO: reuse folder name if not provided
                if os.path.isfile(params["events_file"]):
                    params["events_dict"] = readEventsDict(params["events_file"], absolute=params.get("timestamp", True), sep=params.get("events_sep", "\t"))
                elif os.path.isfile(params.get("input_folder", DATA_REP)+params["events_file"]):
                    params["events_dict"] = readEventsDict(params.get("input_folder", DATA_REP)+params["events_file"], absolute=params.get("timestamp", True), sep=params.get("events_sep", "\t"))

            if params.get("display", False):
                print("DISPLAY %s" % input_name)
                disp_seqs(seqs)
            else:
                fn_basis = "%s%s%s" % (xps_rep, basename, run_id)
                print("RUNNING %s" % input_name)
                mine_seqs(seqs, fn_basis, max_p=params.get("max_p"), out_fmt=params)
        else:
            print("Series %s does not exist!" % series)
