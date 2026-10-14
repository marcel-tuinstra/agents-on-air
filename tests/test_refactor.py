import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from live_feed import LiveFeed
from providers.base import ProviderError
from providers.schema import finalize_snapshot


class LiveFeedTests(unittest.TestCase):
    def test_concurrent_viewers_share_one_refresh_and_keep_latest_only(self):
        now=[0];feed=LiveFeed(clock=lambda:now[0]);self.addCleanup(feed.close)
        entered=threading.Event();release=threading.Event();calls=[]
        def load():
            calls.append(1);entered.set();release.wait(2);return {'revision':len(calls)}
        with ThreadPoolExecutor(max_workers=8) as pool:
            readers=[pool.submit(feed.read,'chat',load) for _ in range(8)]
            self.assertTrue(entered.wait(1));release.set()
            self.assertEqual([r.result(2)['revision'] for r in readers],[1]*8)
        self.assertEqual(len(calls),1)
        entered.clear();release.clear();now[0]=3
        self.assertEqual(feed.read('chat',load)['revision'],1)
        self.assertTrue(entered.wait(1))
        self.assertEqual(feed.read('other',lambda:42),42)
        generation=feed.generation;release.set();feed.wait(generation,2)
        self.assertEqual(feed.read('chat',load)['revision'],2)
        self.assertEqual(len(calls),2)

    def test_failures_recover_without_leaking_unexpected_exception(self):
        now=[0];feed=LiveFeed(clock=lambda:now[0]);self.addCleanup(feed.close)
        def fail(): raise RuntimeError('private path and content')
        with self.assertRaisesRegex(ProviderError,'could not be read'):
            feed.read('chat',fail)
        now[0]=3;generation=feed.generation
        try: feed.read('chat',lambda:'recovered')
        except ProviderError: pass
        feed.wait(generation,2)
        self.assertEqual(feed.read('chat',lambda:'unused'),'recovered')

    def test_cache_is_bounded_and_closed_feed_rejects_reads(self):
        feed=LiveFeed(capacity=2)
        for key in range(10):self.assertEqual(feed.read(key,lambda:key),key)
        self.assertEqual(len(feed.slots),2)
        feed.close()
        with self.assertRaises(ProviderError):feed.read('new',lambda:None)


class SchemaTests(unittest.TestCase):
    def test_shared_limits_ordering_provenance_and_revision(self):
        events=[{'id':str(i),'agentId':'child','at':i} for i in range(501)]
        artifacts=[{'id':'own','agentId':'child'},{'id':'foreign','agentId':'main'}]
        messages=[{'id':str(i),'agentId':'child','at':i,'text':'hello'} for i in range(201)]
        chat={'id':'codex:main'}
        args=dict(chat=chat,agents=[],messages=messages,events=events,artifacts=artifacts,
                  links={'500':['own','foreign']},warnings=['same','same'])
        result=finalize_snapshot(**args)
        self.assertEqual(len(result['messages']),200)
        self.assertEqual(len(result['events']),500)
        self.assertEqual(result['events'][-1]['artifactIds'],['own'])
        self.assertEqual(result['artifacts'],[artifacts[0]])
        self.assertEqual(result['chat']['lastActivityAt'],500)
        self.assertNotIn('lastActivityAt',chat)
        self.assertNotIn('artifactIds',events[-1])
        self.assertEqual(result['warnings'],['same'])
        self.assertTrue(result['historyLimited'])
        self.assertEqual(result['revision'],finalize_snapshot(**args)['revision'])
        messages[-1]={**messages[-1],'text':'changed'}
        self.assertNotEqual(result['revision'],finalize_snapshot(**args)['revision'])

    def test_equal_timestamps_preserve_source_message_order(self):
        messages=[{'id':'z-user','at':10,'text':'Question'}, {'id':'a-agent','at':10,'text':'Answer'}]
        result=finalize_snapshot(chat={},agents=[],messages=messages,events=[],artifacts=[],links={})
        self.assertEqual(result['messages'], messages)
