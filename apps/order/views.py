from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.db import transaction
from django.http import JsonResponse
from django.conf import settings
from django.views.generic import View

from user.models import Address
from goods.models import GoodsSKU
from order.models import OrderInfo,OrderGoods

from django_redis import get_redis_connection
from utils.mixin import LoginRequiredMixin
from datetime import datetime
from alipay import AliPay
import os
# Create your views here.


# /order/place
class OrderPlaceView(LoginRequiredMixin, View):
    '''提交订单页面'''
    def post(self, request):
        '''提交订单页面显示'''
        # 获取登录用户
        user = request.user

        # 接收数据
        sku_ids = request.POST.getlist('sku_ids')
        # 进行校验
        if not sku_ids:
            # 跳转到用户的购物车页面
            return redirect(reverse('cart:show'))

        # 业务处理
        # 获取用户的所有地址信息
        addrs = Address.objects.filter(user=user)

        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id

        # 保存商品的总件数和总金额
        total_count = 0
        total_price = 0
        skus = []
        # 遍历sku_ids获取每一个商品信息
        for sku_id in sku_ids:
            # 根据sku_id获取商品的信息
            sku = GoodsSKU.objects.get(id=sku_id)
            # 获取用户购买的商品的数量
            count = conn.hget(cart_key, sku_id)
            # 计算商品的小计
            amount = sku.price*int(count)
            # 动态给sku对象增加一个属性amount,保存商品的小计
            sku.amount = amount
            # 动态给sku对象增加一个属性count,保存购物车中商品的数目
            sku.count = count
            # 添加
            skus.append(sku)
            # 累加计算商品的总件数和总金额
            total_count += int(count)
            total_price += amount

        # 运费：计算运费的子系统
        transit_price = 10 # 写死

        # 实付款
        total_pay = total_price + transit_price

        # 组织上下文
        sku_ids = ','.join(sku_ids) # 5,6
        context = {'skus':skus,
                   'addrs':addrs,
                   'total_count':total_count,
                   'total_price':total_price,
                   'transit_price':transit_price,
                   'total_pay':total_pay,
                   'sku_ids':sku_ids}

        # 使用模板
        return render(request, 'place_order.html', context)

# 创建订单
# 前端发起ajax post请求
# 前端传递的参数: 地址id->addr_id 支付方式->pay_method 用户要购买商品id的字符串->sku_ids
# /order/commit


# 用户每下一个订单，需要向订单信息表中添加一条信息
# 向订单商品表中添加信息时，用户买了几件商品，需要添加几条记录
# mysql事务: 一组sql操作，要么都成功，要么都失败。
# 高并发: 防止用户下单重复
class OrderCommitView1(View):
    '''订单创建'''
    @transaction.atomic
    def post(self, request):
        '''订单创建'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户未登录
            return JsonResponse({'res':0, 'errmsg':'用户未登录'})

        # 接收数据
        addr_id = request.POST.get('addr_id')
        pay_method = request.POST.get('pay_method')
        sku_ids = request.POST.get('sku_ids') # 5,6

        # 数据校验
        if not all([addr_id, pay_method, sku_ids]):
            return JsonResponse({'res':1, 'errmsg':'数据不完整'})

        # 校验支付方式
        if pay_method not in OrderInfo.PAY_METHODS.keys():
            return JsonResponse({'res':2, 'errmsg':'非法的支付方式'})

        # 校验地址
        try:
            addr = Address.objects.get(id=addr_id)
        except Address.DoesNotExist:
            # 地址不存在
            return JsonResponse({'res':3, 'errmsg':'地址信息错误'})

        # 业务处理
        # 组织订单数据
        # 订单id: 格式:20171122122930+用户id
        order_id = datetime.now().strftime('%Y%m%d%H%M%S')+str(user.id)

        # 运费
        transit_price = 10

        # 总金额和总数目
        total_count = 0
        total_price = 0

        # todo: 设置保存点
        save_id = transaction.savepoint()

        try:
            # todo: 向订单信息表中添加一条记录
            order = OrderInfo.objects.create(order_id=order_id,
                                     user=user,
                                     addr=addr,
                                     pay_method=pay_method,
                                     total_count=total_count,
                                     total_price=total_price,
                                     transit_price=transit_price)

            # todo: 向订单商品表中添加信息时，用户买了几件商品，需要添加几条记录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d'%user.id
            sku_ids = sku_ids.split(',') # [5,6]

            for sku_id in sku_ids:
                # 根据商品的id获取商品的信息
                try:
                    # select * from df_order_goods where id=17 for update;
                    sku = GoodsSKU.objects.select_for_update().get(id=sku_id)
                except GoodsSKU.DoesNotExist:
                    # 商品不存在
                    transaction.savepoint_rollback(save_id)
                    return JsonResponse({'res':4, 'errmsg':'商品不存在'})

                # 从redis中获取用户要购买的商品的数量
                count = conn.hget(cart_key, sku_id)

                print("user:%d stock:%d"%(user.id, sku.stock))
                # 判断商品的库存
                if int(count) > sku.stock:
                    transaction.savepoint_rollback(save_id)
                    return JsonResponse({'res':6, 'errmsg':'商品库存不足'})

                # todo: 向订单商品表中添加一条记录
                OrderGoods.objects.create(order=order,
                                          sku=sku,
                                          count=count,
                                          price=sku.price)

                # todo: 更新对应商品的库存和销量
                sku.stock -= int(count)
                sku.sales += int(count)
                sku.save()

                # todo: 累加计算订单中商品的总数目和总金额
                total_count += int(count)
                amount = sku.price*int(count)
                total_price += amount

            # todo: 更新订单信息表中对应的商品的总件数和总金额
            order.total_count = total_count
            order.total_price = total_price
            order.save()
        except Exception as e:
            # 事务回滚
            transaction.savepoint_rollback(save_id)
            return JsonResponse({'res':7, 'errmsg':'下单失败'})

        # todo: 事务提交
        transaction.savepoint_commit(save_id)

        # todo: 删除用户购物车中的相应记录
        conn.hdel(cart_key, *sku_ids)

        # 返回应答
        return JsonResponse({'res':5, 'message':'订单创建成功'})


class OrderCommitView(View):
    '''订单创建'''
    @transaction.atomic
    def post(self, request):
        '''订单创建'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户未登录
            return JsonResponse({'res':0, 'errmsg':'用户未登录'})

        # 接收数据
        addr_id = request.POST.get('addr_id')
        pay_method = request.POST.get('pay_method')
        sku_ids = request.POST.get('sku_ids') # 5,6

        # 数据校验
        if not all([addr_id, pay_method, sku_ids]):
            return JsonResponse({'res':1, 'errmsg':'数据不完整'})

        # 校验支付方式
        if pay_method not in OrderInfo.PAY_METHODS.keys():
            return JsonResponse({'res':2, 'errmsg':'非法的支付方式'})

        # 校验地址
        try:
            addr = Address.objects.get(id=addr_id)
        except Address.DoesNotExist:
            # 地址不存在
            return JsonResponse({'res':3, 'errmsg':'地址信息错误'})

        # 业务处理
        # 组织订单数据
        # 订单id: 格式:20171122122930+用户id
        order_id = datetime.now().strftime('%Y%m%d%H%M%S')+str(user.id)

        # 运费
        transit_price = 10

        # 总金额和总数目
        total_count = 0
        total_price = 0

        # todo: 设置保存点
        save_id = transaction.savepoint()

        try:
            # todo: 向订单信息表中添加一条记录
            order = OrderInfo.objects.create(order_id=order_id,
                                     user=user,
                                     addr=addr,
                                     pay_method=pay_method,
                                     total_count=total_count,
                                     total_price=total_price,
                                     transit_price=transit_price)

            # todo: 向订单商品表中添加信息时，用户买了几件商品，需要添加几条记录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d'%user.id
            sku_ids = sku_ids.split(',') # [5,6]

            for sku_id in sku_ids:
                for i in range(3):
                    # 根据商品的id获取商品的信息
                    try:
                        # select * from df_order_goods where id=17 for update;
                        sku = GoodsSKU.objects.get(id=sku_id)
                    except GoodsSKU.DoesNotExist:
                        # 商品不存在
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({'res':4, 'errmsg':'商品不存在'})

                    # 从redis中获取用户要购买的商品的数量
                    count = conn.hget(cart_key, sku_id)

                    # 更新时做判断, 判断更新时和之前查到的库存是否一致

                    # todo: 更新对应商品的库存和销量
                    origin_stock = sku.stock
                    news_stock = origin_stock - int(count)
                    news_sales = sku.sales + int(count)
                    # print('user:%d times:%d stock:%d' % (user.id, i, origin_stock))

                    # 判断商品的库存
                    if int(count) > sku.stock:
                        transaction.savepoint_rollback(save_id)
                        return JsonResponse({'res': 6, 'errmsg': '商品库存不足'})

                    # 返回受影响的函数
                    # update df_order_goods set stock=news_stock and sales=new_sales
                    # where id=sku_id and stock = orgin_stock;
                    res = GoodsSKU.objects.filter(id=sku_id, stock=origin_stock).update(stock=news_stock,
                                                                                        sales=news_sales)
                    if res == 0:
                        # 尝试3次
                        if i == 2:
                            transaction.savepoint_rollback(save_id)
                            return JsonResponse({'res': 7, 'errmsg': '下单失败2'})
                        continue

                    # todo: 向订单商品表中添加一条记录
                    OrderGoods.objects.create(order=order,
                                              sku=sku,
                                              count=count,
                                              price=sku.price)

                    # todo: 累加计算订单中商品的总数目和总金额
                    total_count += int(count)
                    amount = sku.price*int(count)
                    total_price += amount

                    # 结束三次循环
                    break

            # todo: 更新订单信息表中对应的商品的总件数和总金额
            order.total_count = total_count
            order.total_price = total_price
            order.save()
        except Exception as e:
            # 事务回滚
            print(e)
            transaction.savepoint_rollback(save_id)
            return JsonResponse({'res':7, 'errmsg':'下单失败'})

        # todo: 事务提交
        transaction.savepoint_commit(save_id)

        # todo: 删除用户购物车中的相应记录
        conn.hdel(cart_key, *sku_ids)

        # 返回应答
        return JsonResponse({'res':5, 'message':'订单创建成功'})


# 前端 ajax post访问/order/pay
# 传递的参数:订单id(order_id)
class OrderPayView(View):
    '''订单支付'''
    def post(self, request):
        '''订单支付'''
        # 登录判断
        user = request.user
        if not user.is_authenticated():
            return JsonResponse({'res':0, 'errmsg':'用户未登录'})

        # 接收参数
        order_id = request.POST.get('order_id')

        # 校验参数
        if not order_id:
            return JsonResponse({'res':1, 'errmsg':'订单id为空'})

        try:
            order = OrderInfo.objects.get(order_id=order_id,
                                  user=user,
                                  pay_method=3,
                                  order_status=1)
        except OrderInfo.DoesNotExist:
            # 订单不存在
            return JsonResponse({'res': 2, 'errmsg': '订单id出错'})

        # 业务处理:调用支付宝的支付接口
        # 初始化
        alipay = AliPay(
            appid="2016082600315021",
            app_notify_url=None,  # 默认回调url
            app_private_key_path=os.path.join(settings.BASE_DIR, 'apps/order/app_private_key.pem'),
            alipay_public_key_path=os.path.join(settings.BASE_DIR, 'apps/order/alipay_public_key.pem'),  # 支付宝的公钥，验证支付宝回传消息使用，不是你自己的公钥,
            sign_type="RSA2",  # RSA 或者 RSA2
            debug=True  # 默认False
        )

        # 调用支付宝下单支付接口 alipay.trade.page.pay
        # 电脑网站支付，需要跳转到https://openapi.alipaydev.com/gateway.do? + order_string
        total_pay = order.total_price + order.transit_price # Decimal
        order_string = alipay.api_alipay_trade_page_pay(
            out_trade_no=order_id,
            total_amount=str(total_pay),
            subject='天天生鲜%s'%order_id,
            return_url=None,
            notify_url=None  # 可选, 不填则使用默认notify url
        )

        # 返回应答
        pay_url = 'https://openapi.alipaydev.com/gateway.do?' + order_string
        return JsonResponse({'res':3, 'pay_url':pay_url})























