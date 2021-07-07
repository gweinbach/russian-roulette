from gevent import monkey
monkey.patch_all()
import gevent
import unittest

from discord.callback_holder import Callback, CallbackHolder


class TestCallbackHolder(unittest.TestCase):

    def test_callback(self):

        # Given a Caller
        class C:
            def __init__(self):
                self.value = 0

            def increment(self,
                          inc: int = 1):
                self.value += inc

        caller = C()

        # Given a Callback
        REARM_TIMEOUT=2
        callback = Callback(caller, C.increment, rearm_timeout_in_s=REARM_TIMEOUT)

        # When callback is fired without argument
        greenlet = callback.fire()

        # Then method is not called before we join greenlets
        self.assertEqual(caller.value, 0)

        # Then method is called asynchronously (with default argument value)
        greenlet and greenlet.join()
        self.assertEqual(caller.value, 1)



        # When callback is fired with arguments
        greenlet = callback.fire(10)

        # Then method is not called before we join greenlets
        self.assertEqual(caller.value, 1)

        # Then method is called asynchronously with given argument value
        greenlet and greenlet.join()
        self.assertEqual(caller.value, 11)



        # When callback is fired with arguments and user
        greenlet = callback.fire(10, user_id="toto")

        # Then method is called asynchronously...
        greenlet and greenlet.join()
        self.assertEqual(caller.value, 21)


        # When callback is fired with arguments and same user before rearm timeout
        greenlet = callback.fire(10, user_id="toto")

        # Then method is not called
        greenlet and greenlet.join()
        self.assertEqual(caller.value, 21)


        # When we wait long enough
        gevent.sleep(REARM_TIMEOUT)
        # When callback is fired again with arguments and same user
        greenlet = callback.fire(10, user_id="toto")

        # Then method is called
        greenlet and greenlet.join()
        self.assertEqual(caller.value, 31)



    def test_callback_holder(self):

        # Given a Callback Holder
        callback_holder = CallbackHolder()

        # Given a Caller
        class C:
            def __init__(self):
                self.value = 0

            def increment(self,
                          inc: int = 1):
                self.value += inc

        caller = C()

        # Given a Key
        key = "12345"

        # When Callback is registered under key
        callback_holder.register_callback(key=key,
                                          caller=caller,
                                          callback_method=C.increment,
                                          rearm_timeout_in_s=5)

        # When Callback is retrieved with incorrect key value
        callback = callback_holder.matching_callback(key + key)

        # Then nothing is retrieved
        self.assertEqual(callback, None)


        
        # When Callback is retrieved with  matching key value
        callback = callback_holder.matching_callback(key)

        # Then Callback can be retrieved with matching key
        self.assertEqual(callback, Callback(caller, C.increment, 5))
        self.assertNotEqual(callback, Callback(caller, C.increment, 6))
        

if __name__ == '__main__':
    unittest.main()
