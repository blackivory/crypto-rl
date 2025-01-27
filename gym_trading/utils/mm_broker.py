# mm_broker.py
#
#   Inventory and risk management for the MarketMaker environment
#
#
import logging
from configurations.configs import BROKER_FEE
import numpy as np


logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s')
logger = logging.getLogger('mm_broker')


class Order(object):
    _size = 1000.
    _id = 0

    def __init__(self, ccy='BTC-USD', side='long', price=0.0, step=-1,
                 queue_ahead=100.):
        self.ccy = ccy
        self.side = side
        self.price = price
        self.step = step
        self.executed = 0.
        Order._id += 1
        self.id = Order._id
        self.queue_ahead = queue_ahead
        self.executions = dict()
        self.average_exectution_price = -1.

    def __str__(self):
        return ' %s-%s | %.3f | %i | %.2f | %.2f' % \
               (self.ccy, self.side, self.price, self.step, self.executed,
                self.queue_ahead)

    def reduce_queue_ahead(self, executed_volume=100.):
        self.queue_ahead -= executed_volume
        if self.queue_ahead < 0.:
            splash = 0. - self.queue_ahead
            self.queue_ahead = 0.
            self.process_executions(volume=splash)

    def process_executions(self, volume=100.):
        self.executed += volume
        overflow = 0.
        if self.is_filled:
            overflow = self.executed - Order._size
            # print('executed before = {}'.format(self.executed))
            self.executed -= overflow
            # print('executed after = {}'.format(self.executed))
        _price = float(self.price)
        if _price in self.executions:
            self.executions[_price] += volume - overflow
        else:
            self.executions[_price] = volume - overflow

    def get_average_execution_price(self):
        total_volume = 0.
        for k, v in self.executions.items():
            total_volume += v / k
        # print('acquired {} position size of {}'.format(self.side, total_volume))
        self.average_exectution_price = 0.
        for k, v in self.executions.items():
            self.average_exectution_price += k * ((v / k) / total_volume)
        self.average_exectution_price = round(self.average_exectution_price, 4)
        # print('{} avg_price is {} | {}'.format(self.side,
        #                                        self.average_exectution_price,
        #                                        self.price))
        return self.average_exectution_price

    @property
    def is_filled(self):
        return self.executed >= Order._size

    @property
    def is_first_in_queue(self):
        return self.queue_ahead <= 0.


class PositionI(object):
    """
    Position class keeps track the agent's trades
    and provides stats (e.g., pnl)
    """
    # TODO Add net position to calculate pnl
    def __init__(self, side='long', max_position=1):
        self.max_position_count = max_position
        self.positions = []
        self.order = None
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.full_inventory = False
        self.total_exposure = 0.0
        self.side = side
        self.average_price = 0.0
        self.reward_size = 1 / self.max_position_count
        self.total_trade_count = 0

    def reset(self):
        self.positions.clear()
        self.order = None
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        self.full_inventory = False
        self.total_exposure = 0.0
        self.average_price = 0.0
        self.total_trade_count = 0

    @property
    def position_count(self):
        return len(self.positions)

    def add_order(self, order):
        if not self.full_inventory:
            if self.order is None:
                logger.debug('Opened new order={}'.format(order))
                self.order = order
            else:
                logger.debug('Updating existing order{} '
                             '--> {}'.format(self.order, order))
                self.order.price = np.copy(order.price)
                self.order.queue_ahead = np.copy(order.queue_ahead)
                self.order.id = np.copy(order.id)

            return True
        else:
            logger.debug("{} order rejected. "
                         "Already at max position "
                         "limit ({})".format(self.side, self.max_position_count))
            return False

    def cancel_order(self):
        if self.order is None:
            logger.debug('No {} open orders to cancel.'.format(self.side))
            return False
        logger.debug('Cancelling order ({})'.format(self.order))
        self.order = None
        return True

    def step(self, bid_price=100., ask_price=100., buy_volume=1000.,
             sell_volume=1000., step=100):
        if self.order is None:
            return False

        if self.order.side == 'long':
            if bid_price <= self.order.price:
                if self.order.is_first_in_queue:
                    self.order.process_executions(buy_volume)
                else:
                    self.order.reduce_queue_ahead(buy_volume)

        elif self.order.side == 'short':
            if ask_price >= self.order.price:
                if self.order.is_first_in_queue:
                    self.order.process_executions(sell_volume)
                else:
                    self.order.reduce_queue_ahead(sell_volume)

        if self.order.is_filled:
            self.positions.append(self.order)
            self.total_exposure += self.order.get_average_execution_price()
            self.average_price = self.total_exposure / self.position_count
            self.full_inventory = self.position_count >= self.max_position_count
            steps_to_fill = step - self.order.step
            logger.debug('FILLED %s order #%i at %.3f after %i steps on %i.' %
                         (self.order.side, self.order.id, self.order.price,
                          steps_to_fill, step))
            self.order = None  # set the slot back to no open orders
            return True

        return False

    def pop_position(self):
        if self.position_count > 0:
            position = self.positions.pop()

            # update positions attributes
            self.total_exposure -= position.average_exectution_price
            if self.position_count > 0:
                self.average_price = self.total_exposure / self.position_count
            else:
                self.average_price = 0

            self.full_inventory = self.position_count >= self.max_position_count
            logger.debug('---%s position #%i @ %.4f has been netted out.' % (
                self.side, position.id, position.price))
            return position
        else:
            logger.info('Error. No {} pop_position to remove.'.format(self.side))
            return None

    def remove_position(self, midpoint=100.):
        pnl = 0.
        if self.position_count > 0:
            order = self.positions.pop(0)
            # Calculate PnL
            if self.side == 'long':
                pnl = (midpoint - order.price) / order.price
            elif self.side == 'short':
                pnl = (order.price - midpoint) / order.price
            # Add Profit and Loss to total
            self.realized_pnl += pnl
            # update positions attributes
            self.total_exposure -= order.average_exectution_price
            if self.position_count > 0:
                self.average_price = self.total_exposure / self.position_count
            else:
                self.average_price = 0
            self.full_inventory = self.position_count >= self.max_position_count
            self.total_trade_count += 1  # entry and exit = two trades
            logger.debug('Closing %s position #%i. PnL=%.4f\n' %
                        (self.side, order.id, pnl))
            return pnl
        else:
            logger.info('Error. No {} positions to remove.'.format(self.side))
            return pnl

    def flatten_inventory(self, midpoint=100.):
        logger.debug('{} is flattening inventory of {}'.format(self.side,
                                                               self.position_count))
        prev_realized_pnl = self.realized_pnl
        if self.position_count < 1:
            return -0.00000000001

        while self.position_count > 0:
            self.remove_position(midpoint=midpoint)
            self.realized_pnl -= BROKER_FEE  # marker order fee

        return self.realized_pnl - prev_realized_pnl  # net change in PnL

    def get_unrealized_pnl(self, midpoint=100.):
        if self.position_count == 0:
            return 0.0

        difference = 0.0
        if self.side == 'long':
            difference = midpoint - self.average_price
        elif self.side == 'short':
            difference = self.average_price - midpoint

        if difference == 0.0:
            unrealized_pnl = 0.0
        else:
            unrealized_pnl = difference / self.average_price

        return unrealized_pnl

    def get_distance_to_midpoint(self, midpoint=100.):
        if self.order is None:
            return 0.
        if self.side == 'long':
            return (midpoint - self.order.price) / self.order.price
        elif self.side == 'short':
            return (self.order.price - midpoint) / self.order.price


class Broker(object):
    '''
    Broker class is a wrapper for the PositionI class
    and is implemented in `gym_trading.py`
    '''
    reward_scale = BROKER_FEE * 2.

    def __init__(self, max_position=1):
        self.long_inventory = PositionI(side='long', max_position=max_position)
        self.short_inventory = PositionI(side='short', max_position=max_position)

    def reset(self):
        self.long_inventory.reset()
        self.short_inventory.reset()

    def add(self, order):
        if order.side == 'long':
            return self.long_inventory.add_order(order=order)
        elif order.side == 'short':
            return self.short_inventory.add_order(order=order)
        else:
            logger.warning('Error. Broker trying to add to '
                           'the wrong side [{}]'.format(order.side))
            return False

    def get_unrealized_pnl(self, midpoint=100.):
        long_pnl = self.long_inventory.get_unrealized_pnl(midpoint=midpoint)
        short_pnl = self.short_inventory.get_unrealized_pnl(midpoint=midpoint)
        return long_pnl + short_pnl

    def get_realized_pnl(self):
        return self.short_inventory.realized_pnl + self.long_inventory.realized_pnl

    def get_total_pnl(self, midpoint):
        total_pnl = self.get_unrealized_pnl(midpoint=midpoint) + \
                    self.get_realized_pnl()
        return total_pnl

    @property
    def long_inventory_count(self):
        return self.long_inventory.position_count

    @property
    def short_inventory_count(self):
        return self.short_inventory.position_count

    def flatten_inventory(self, bid_price=100., ask_price=100.):
        total_pnl = self.long_inventory.flatten_inventory(midpoint=bid_price)
        total_pnl += self.short_inventory.flatten_inventory(midpoint=ask_price)
        if total_pnl != 0.:
            total_pnl /= Broker.reward_scale
        return total_pnl

    def step(self,  bid_price=100., ask_price=100., buy_volume=1000.,
             sell_volume=1000., step=100):
        pnl = 0.

        if self.long_inventory.step(bid_price=bid_price, ask_price=ask_price,
                                    buy_volume=buy_volume,
                                    sell_volume=sell_volume, step=step):
            # check if we can net the inventory
            if self.short_inventory_count > 0:
                # net out the inventory
                new_position = self.long_inventory.pop_position()
                pnl += self.short_inventory.remove_position(
                    midpoint=new_position.price)
                # if pnl != 0.:
                #     pnl /= Broker.reward_scale

        if self.short_inventory.step(bid_price=bid_price, ask_price=ask_price,
                                     buy_volume=buy_volume,
                                     sell_volume=sell_volume, step=step):
            # check if we can net the inventory
            if self.long_inventory_count > 0:
                # net out the inventory
                new_position = self.short_inventory.pop_position()
                pnl += self.long_inventory.remove_position(
                    midpoint=new_position.price)
                # if pnl != 0.:
                #     pnl /= Broker.reward_scale

        return pnl / Broker.reward_scale

    def get_short_order_distance_to_midpoint(self, midpoint=100.):
        return self.short_inventory.get_distance_to_midpoint(midpoint=midpoint) / \
               Broker.reward_scale

    def get_long_order_distance_to_midpoint(self, midpoint=100.):
        return self.long_inventory.get_distance_to_midpoint(midpoint=midpoint) / \
               Broker.reward_scale

    def get_queues_ahead_features(self):
        buy_queue = short_queue = 0.

        if self.long_inventory.order:
            queue = self.long_inventory.order.queue_ahead
            executions = max(self.long_inventory.order.executed, 0.0001)
            trade_size = self.long_inventory.order._size
            buy_queue = (executions - queue) / (queue + trade_size)

        if self.short_inventory.order:
            queue = self.short_inventory.order.queue_ahead
            executions = max(self.short_inventory.order.executed, 0.0001)
            trade_size = self.short_inventory.order._size
            short_queue = (executions - queue) / (queue + trade_size)

        return buy_queue, short_queue

    def get_total_trade_count(self):
        return self.long_inventory.total_trade_count + \
               self.short_inventory.total_trade_count
