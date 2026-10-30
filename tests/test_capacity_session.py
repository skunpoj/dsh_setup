import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from capacity_session import runtime_units, session_plan

A = 'dsh-u-' + 'a' * 16 + '-secure'
B = 'dsh-u-' + 'b' * 16 + '-secure'
C = 'dsh-u-' + 'c' * 16 + '-internet'


class SessionPlanTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.runtimes = {A: {'replicas': 0, 'ready': 0}, B: {'replicas': 0, 'ready': 0}, C: {'replicas': 1, 'ready': 1}}

    def demand(self, entries, age=0):
        iso = lambda s: (self.now - timedelta(seconds=s)).isoformat()
        return {'observedAt': iso(age), 'runtimes': {n: {'requestedAt': iso(r), 'lastActivityAt': iso(a)} for n, (r, a) in entries.items()}}

    def plan(self, demand, units=4):
        return session_plan(demand, self.runtimes, units, self.now, 3600)

    def test_first_come_first_served_when_short(self):
        r = self.plan(self.demand({A: (30, 1), B: (60, 1), C: (10, 1)}), units=1)
        self.assertEqual(r['scaleUp'], [B], 'Earliest request starts first')
        self.assertEqual(r['runtimes'][A], {'state': 'waiting', 'position': 1})
        self.assertEqual(r['summary']['waiting'], 1)

    def test_idle_and_undemanded_runtimes_stop(self):
        r = self.plan(self.demand({A: (30, 1)}))
        self.assertEqual(r['scaleDown'], [C], 'A running runtime nobody uses stops')
        self.assertEqual(r['scaleUp'], [A])
        idle = self.plan(self.demand({C: (9000, 3700)}))
        self.assertEqual(idle['scaleDown'], [C], 'Past the idle timeout it stops')

    def test_active_runtime_keeps_running(self):
        r = self.plan(self.demand({C: (9000, 5)}))
        self.assertEqual(r['scaleDown'], [])
        self.assertEqual(r['runtimes'][C], {'state': 'running'})

    def test_missing_or_stale_demand_never_stops_anyone(self):
        for demand in [{}, self.demand({}, age=120), {'observedAt': 'not-a-time'}]:
            r = self.plan(demand)
            self.assertEqual((r['scaleDown'], r['scaleUp']), ([], []))
            self.assertEqual(r['runtimes'][C], {'state': 'running'})

    def test_starts_are_bounded_per_round(self):
        many = {f'dsh-u-{i:016x}-secure': {'replicas': 0, 'ready': 0} for i in range(10)}
        demand = self.demand({n: (i, 1) for i, n in enumerate(many)})
        r = session_plan(demand, many, 100, self.now, 3600)
        self.assertEqual(len(r['scaleUp']), 4)

    def test_rejects_foreign_names_and_unsafe_timeouts(self):
        with self.assertRaises(ValueError):
            session_plan({}, {'litellm': {'replicas': 1}}, 1, self.now, 3600)
        with self.assertRaises(ValueError):
            session_plan({}, self.runtimes, 1, self.now, 10)

    def test_units_need_compute_but_not_new_storage(self):
        rows = {k: {'available': a, 'reserve': r, 'pairBudget': p} for k, a, r, p in
                [('cpu', 3.0, 2, .5), ('memoryGiB', 100, 32, 2.25), ('pods', 40, 10, 2), ('storageGiB', 0, 32, 23)]}
        self.assertEqual(runtime_units({'capacityInputs': {'resources': rows}}), 4)
        rows['cpu']['available'] = float('nan')
        self.assertEqual(runtime_units({'capacityInputs': {'resources': rows}}), 0)
        self.assertEqual(runtime_units({}), 0)


class PodProgressTests(unittest.TestCase):
    def pod(self, conditions=(), init=(), containers=(), deleting=False):
        meta = {'creationTimestamp': '2026-10-30T06:00:00Z'}
        if deleting:
            meta['deletionTimestamp'] = 'x'
        return {'metadata': meta, 'status': {'conditions': [{'type': t, 'status': s, **({'reason': r} if r else {})} for t, s, r in conditions],
                'initContainerStatuses': list(init), 'containerStatuses': list(containers)}}

    def test_stages_progress_in_order(self):
        from capacity_session import pod_progress
        waiting = lambda r: {'state': {'waiting': {'reason': r}}}
        running = {'state': {'running': {}}}
        cases = [
            ([], 'scheduling', 10),
            ([self.pod([('PodScheduled', 'False', 'Unschedulable')])], 'scheduling', 15),
            ([self.pod([('PodScheduled', 'True', None), ('Initialized', 'False', None)], init=[waiting('PodInitializing')])], 'preparing', 35),
            ([self.pod([('PodScheduled', 'True', None), ('Initialized', 'True', None)], containers=[waiting('ContainerCreating')])], 'pulling-image', 45),
            ([self.pod([('PodScheduled', 'True', None), ('Initialized', 'True', None)], containers=[running, waiting('Waiting')])], 'starting-containers', 65),
            ([self.pod([('PodScheduled', 'True', None), ('Initialized', 'True', None), ('Ready', 'False', None)], containers=[running, running])], 'starting-dsh', 85),
            ([self.pod([('PodScheduled', 'True', None), ('Initialized', 'True', None), ('Ready', 'True', None)], containers=[running])], 'ready', 100),
        ]
        last = 0
        for pods, stage, percent in cases:
            p = pod_progress(pods)
            self.assertEqual((p['stage'], p['percent']), (stage, percent))
            self.assertGreaterEqual(p['percent'], last)
            last = p['percent']

    def test_failures_and_terminating_pods(self):
        from capacity_session import pod_progress
        crash = self.pod([('PodScheduled', 'True', None)], containers=[{'state': {'waiting': {'reason': 'CrashLoopBackOff'}}}])
        self.assertEqual(pod_progress([crash])['stage'], 'failed')
        self.assertEqual(pod_progress([crash])['detail'], 'CrashLoopBackOff')
        self.assertEqual(pod_progress([self.pod(deleting=True)])['stage'], 'scheduling', 'A terminating old pod is ignored')


if __name__ == '__main__':
    unittest.main()
