from django.shortcuts import render
from django.views.generic import View
from django.http import JsonResponse

from goods.models import GoodsSKU
from utils.mixin import LoginRequiredMixin
from django_redis import get_redis_connection
# Create your views here.
# 采用ajax发起请求
# 浏览器需要传递的数据: 商品id->sku_id 商品数目->count
# get:参数跟在url后面 /cart/add?参数=值
# post:参数在请求体中
# url传参数:url捕获参数
# 如果涉及到数据的修改，采用post方式
# 如果涉及到数据的获取，采用get方式

# 1.请求方式(post,get)
# 2.确定浏览器需要传递的参数
# 3.返回的数据的格式


# ajax发起的请求都在后台，浏览器中是看不到的
class CartAddView(View):
    '''购物车记录添加'''
    def post(self, request):
        '''购物车记录添加'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户没有登录
            return JsonResponse({'res':0, 'errmsg':'请先登录'})

        # 接收数据
        sku_id = request.POST.get('sku_id')
        count = request.POST.get('count')

        # 数据校验
        if not all([sku_id, count]):
            return JsonResponse({'res':1, 'errmsg':'数据不完整'})

        # 校验商品的数目
        try:
            count = int(count)
        except Exception as e:
            # 商品数目出错
            return JsonResponse({'res':2, 'errmsg':'商品数目出错'})

        # 校验商品是否存在
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 商品不存在
            return JsonResponse({'res':3, 'errmsg':'商品不存在'})

        # 业务处理:添加购物车记录
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id
        # 先尝试获取cart_key中sku_id的值
        sku_count = conn.hget(cart_key, sku_id)
        if sku_count:
            # 如果购物车中商品已存在，数目需要累加
            count += int(sku_count)

        # 校验商品的库存
        if count > sku.stock:
            return JsonResponse({'res': 4, 'errmsg': '商品库存不足'})

        # 添加记录
        conn.hset(cart_key, sku_id, count)

        # 获取用户购物车中商品的条目数
        cart_count = conn.hlen(cart_key)

        # 返回应答
        return JsonResponse({'res':5,'cart_count':cart_count, 'message':'添加成功'})


# /cart/
class CartInfoView(LoginRequiredMixin, View):
    '''购物车页面显示'''
    def get(self, request):
        '''显示'''
        # 获取登录用户
        user = request.user
        # 获取用户购物车中商品的信息
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id
        # {'商品id':商品数目, ....}
        cart_dict = conn.hgetall(cart_key)

        skus = []
        # 分别保存用户购物车中商品的总件数和总价格
        total_count = 0
        total_price = 0
        for sku_id,count in cart_dict.items():
            # 根据sku_id获取商品的信息
            sku = GoodsSKU.objects.get(id=sku_id)
            # 计算商品的小计
            amount = sku.price*int(count)
            # 动态给sku对象增加一个属性amount,保存商品的小计
            sku.amount = amount
            # 动态给sku对象增加一个属性count,保存购物车中商品的数目
            sku.count = count
            # 添加
            skus.append(sku)
            # 累加计算商品的总件数和总价格
            total_count += int(count)
            total_price += amount

        # 组织上下文
        context = {'total_count':total_count,
                   'total_price':total_price,
                   'skus':skus}

        # 使用模板
        return render(request, 'cart.html', context)


# 更新购物车记录
# 采用ajax post 请求
# 前端需要传递的参数: 商品id->sku_id 商品数量:count
# /cart/update
class CartUpdateView(View):
    '''购物车记录更新'''
    def post(self, request):
        '''购物车记录更新'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户没有登录
            return JsonResponse({'res': 0, 'errmsg': '请先登录'})

        # 接收数据
        sku_id = request.POST.get('sku_id')
        count = request.POST.get('count')

        # 进行校验
        if not all([sku_id, count]):
            return JsonResponse({'res':1, 'errmsg':'数据不完整'})

        # 校验商品的数目
        try:
            count = int(count)
        except Exception as e:
            # 商品数目出错
            return JsonResponse({'res': 2, 'errmsg': '商品数目出错'})

        # 校验商品是否存在
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 商品不存在
            return JsonResponse({'res': 3, 'errmsg': '商品不存在'})

        # 业务处理:购物记录更新
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id

        # 校验商品的库存
        if count > sku.stock:
            return JsonResponse({'res':4, 'errmsg':'商品库存不足'})

        # 更新
        conn.hset(cart_key, sku_id, count)

        # 获取购物车中全部商品的总件数
        total_count = 0
        vals = conn.hvals(cart_key)
        for val in vals:
            total_count += int(val)

        # 返回应答
        return JsonResponse({'res':5, 'total_count':total_count, 'message':'更新成功'})


# 删除购物车记录
# 采用ajax post 请求
# 前端需要传递的参数: 商品id->sku_id
# /cart/delete
class CartDeleteView(View):
    '''购物车记录删除'''
    def post(self, request):
        '''购物车记录删除'''
        # 判断用户是否登录
        user = request.user
        if not user.is_authenticated():
            # 用户没有登录
            return JsonResponse({'res': 0, 'errmsg': '请先登录'})

        # 接收数据
        sku_id = request.POST.get('sku_id')

        # 校验参数
        if not sku_id:
            return JsonResponse({'res':1, 'errmsg':'参数不完整'})

        # 校验商品是否存在
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 商品不存在
            return JsonResponse({'res':2, 'errmsg':'商品不存在'})

        # 业务处理:删除购物车记录
        conn = get_redis_connection('default')
        cart_key = 'cart_%d'%user.id

        # 删除:从cart_key对应的元素中删除sku_id
        conn.hdel(cart_key, sku_id)

        # 获取购物车中全部商品的总件数
        total_count = 0
        vals = conn.hvals(cart_key)
        for val in vals:
            total_count += int(val)

        # 返回应答
        return JsonResponse({'res':3, 'total_count':total_count, 'message':'删除成功'})












