import unittest
import numpy as np
from datetime import datetime as dt
import gym
from gym_trading.envs.price_jump import PriceJump
import gym_trading


class MyTestCase(unittest.TestCase):

    def test_price_jump_gym(self):
        start_time = dt.now()

        config = {
            'training': True,
            'fitting_file': 'ETH-USD_2018-12-31.xz',
            'testing_file': 'ETH-USD_2019-01-01.xz',
            'step_size': 1,
            'max_position': 1,
            'window_size': 5,
            'seed': 1,
            'action_repeats': 10,
            'format_3d': False,
            'z_score': False,
        }

        env = gym.make(PriceJump.id, **config)
        total_reward = 0.0

        i = 0
        done = False
        env.reset()

        while not done:
            i += 1

            if i % 200 == 0:
                action = np.random.randint(3)
            else:
                action = 0

            state, reward, done, _ = env.step(action)
            total_reward += reward

            # if reward != 0.0:
            #     print('reward = %.4f' % reward)

            if done:
                elapsed = (dt.now() - start_time).seconds
                print('Done on step #%i @ %i steps/second' %
                            (i, i*env.action_repeats // elapsed))
                break

        print('Total reward: %.4f' % total_reward)
        self.assertEqual(True, done)


if __name__ == '__main__':
    unittest.main()
