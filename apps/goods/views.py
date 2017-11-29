from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.views.generic import View
from django.core.paginator import Paginator
from django.core.cache import cache
from goods.models import GoodsType, GoodsSKU, IndexGoodsBanner, IndexPromotionBanner, IndexTypeGoodsBanner
from order.models import OrderGoods
from django_redis import get_redis_connection
from utils.mixin import LoginRequiredMixin
# Create your views here.


class IndexView(View):
    '''首页'''
    def get(self, request):
        '''显示'''
        # 尝试从缓存中获取数据
        context = cache.get('index_page_data')

        if context is None:
            print('设置了缓存')
            # 缓存中没有数据
            # 获取商品的分类信息
            types = GoodsType.objects.all()

            # 获取首页轮播商品信息
            goods_banners = IndexGoodsBanner.objects.all().order_by('index')

            # 获取首页促销活动信息
            promotion_banners = IndexPromotionBanner.objects.all().order_by('index')

            # 获取首页分类商品展示信息
            # type_goods_banners = IndexTypeGoodsBanner.objects.all()
            # for type in types:
            #     for banner in type_goods_banners:
            #         if type == banner.type:

            for type in types: # GoodsType->对象
                image_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=1).order_by('index')
                title_banners = IndexTypeGoodsBanner.objects.filter(type=type, display_type=0).order_by('index')
                # 动态给type对象增加属性，分别保存首页展示的图片商品信息和标题商品信息
                type.image_banners = image_banners
                type.title_banners = title_banners

            # 组织模板上下文
            context = {'types': types,
                        'goods_banners': goods_banners,
                        'promotion_banners': promotion_banners}

            # 设置缓存数据
            # 缓存名称  缓存数据  过期时间
            cache.set('index_page_data', context, 3600)

        # 获取购物车商品数量
        cart_count = 0
        # 判断用户是否登录
        user = request.user
        if user.is_authenticated():
            # 用户已登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d'%user.id
            cart_count = conn.hlen(cart_key)

        context.update(cart_count=cart_count)

        return render(request, 'index.html', context)


# /goods/商品id
class DetailView(View):
    '''商品详情页'''
    def get(self, request, sku_id):
        '''显示商品详情页面'''
        # 根据sku_id获取商品的信息
        try:
            sku = GoodsSKU.objects.get(id=sku_id)
        except GoodsSKU.DoesNotExist:
            # 商品不存在
            return redirect(reverse('goods:index'))

        # 获取商品分类信息
        types = GoodsType.objects.all()

        # 获取商品评论信息
        sku_orders = OrderGoods.objects.filter(sku=sku).exclude(comment='')[:30]

        # 获取新品信息
        new_skus = GoodsSKU.objects.filter(type=sku.type).order_by('-create_time')[:2]

        # 获取商品的其他规格
        same_spu_skus = GoodsSKU.objects.filter(goods=sku.goods).exclude(id=sku_id)

        # 获取购物车中商品数目
        cart_count = 0
        # 判断用户是否登录
        user = request.user
        if user.is_authenticated():
            # 用户已登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d' % user.id
            cart_count = conn.hlen(cart_key)

            # 添加历史浏览记录
            conn = get_redis_connection('default')
            history_key = 'history_%d'%user.id
            # 先尝试移除列表中sku_id
            conn.lrem(history_key, 0, sku_id)
            # 将sku_id插入到列表的左侧
            conn.lpush(history_key, sku_id)
            # 只保留用户浏览的最新5个商品
            conn.ltrim(history_key, 0, 4)

        # 组织模板上下文
        context = {'sku':sku, 'types':types,
                   'sku_orders':sku_orders,
                   'new_skus':new_skus,
                   'same_spu_skus': same_spu_skus,
                   'cart_count':cart_count}

        # 使用模板
        return render(request, 'detail.html', context)


# restful api设计
# 种类id 页码 排序方式
# /list/种类id/1
# /list/种类id/页码/排序的方式
# /list/种类id/页码?sort=排序方式
class ListView(View):
    '''详情页'''
    def get(self, request, type_id, page):
        '''显示详情页'''
        try:
            type = GoodsType.objects.get(id=type_id)
        except GoodsType.DoesNotExist:
            # 种类信息不存在
            return redirect(reverse('goods:index'))

        # 获取商品分类信息
        types = GoodsType.objects.all()

        # 获取排序方式sort
        sort = request.GET.get('sort')

        # 获取分类商品的信息
        # sort=default->默认排序方式
        # sort=price->按照价格排序
        # sort=hot->按照商品的销量进行排序
        if sort == 'price':
            skus = GoodsSKU.objects.filter(type=type).order_by('price')
        elif sort == 'hot':
            skus = GoodsSKU.objects.filter(type=type).order_by('-sales')
        else:
            sort='default'
            skus = GoodsSKU.objects.filter(type=type).order_by('-id')

        # 对数据进行分页
        paginator = Paginator(skus, 1)

        # 处理页码
        try:
            page = int(page)
        except Exception as e:
            # 页码出错
            page = 1

        if page > paginator.num_pages:
            page = 1

        # 获取第page页的内容
        # 返回的是Page类的实例对象
        skus_page = paginator.page(page)

        # 控制页码的列表，最多在页面上只显示5个页码
        # 1.总页数小于5页，显示所有页码
        # 2.当前页属于前3页，显示前5页
        # 3.当前页属于后3页，显示后5页
        # 4.其他情况，显示当前页的前2页，当前页，当前页后2页
        num_pages = paginator.num_pages
        if num_pages < 5:
            pages = range(1, num_pages+1)
        elif page <= 3:
            pages = range(1, 6)
        elif num_pages - page <= 2:
            pages = range(num_pages-4, num_pages+1)
        else:
            pages = range(page-2, page+3)

        # 获取新品信息
        new_skus = GoodsSKU.objects.filter(type=type).order_by('-create_time')[:2]

        # 获取购物车中商品数目
        cart_count = 0
        # 判断用户是否登录
        user = request.user
        if user.is_authenticated():
            # 用户已登录
            conn = get_redis_connection('default')
            cart_key = 'cart_%d' % user.id
            cart_count = conn.hlen(cart_key)

        # 组织模板上下文
        context = {'type':type, 'types':types,
                   'skus_page':skus_page,
                   'new_skus':new_skus,
                   'cart_count':cart_count,
                   'pages':pages,
                   'sort':sort}

        # 使用模板
        return render(request, 'list.html', context)
