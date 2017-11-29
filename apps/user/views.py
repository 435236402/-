from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponse
from django.core.paginator import  Paginator
from django.views.generic import View
from django.core.mail import send_mail

from user.models import User, Address
from goods.models import GoodsSKU
from order.models import OrderInfo, OrderGoods

from utils.mixin import LoginRequiredMixin
from celery_tasks.tasks import send_register_active_email
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from itsdangerous import SignatureExpired
import re
import time
from django_redis import get_redis_connection
# Create your views here.


# GET POST PUT DELETE
# /user/register
def register(request):
    '''注册'''
    if request.method == 'GET':
        # 显示注册页面'
        return render(request, 'register.html')
    else:
        # 进行注册处理
        # 接收数据
        username = request.POST.get('user_name')
        password = request.POST.get('pwd')
        email = request.POST.get('email')
        allow = request.POST.get('allow')

        # 进行数据校验
        if not all([username, password, email]):
            # 数据不完整
            return render(request, 'register.html', {'errmsg': '数据不完整'})

        if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
            return render(request, 'register.html', {'errmsg': '邮箱不合法'})

        if allow != 'on':
            return render(request, 'register.html', {'errmsg': '请同意协议'})

        # 进行业务处理：完成用户的注册
        user = User.objects.create_user(username, email, password)
        user.is_active = 0
        user.save()

        # 返回应答,跳转到首页
        return redirect(reverse('goods:index'))


def register_handle(request):
    '''用户注册处理'''
    # 接收数据
    username = request.POST.get('user_name')
    password = request.POST.get('pwd')
    email = request.POST.get('email')
    allow = request.POST.get('allow')

    # 进行数据校验, 防止一些非法的请求
    if not all([username, password, email]):
        # 数据不完整
        return render(request, 'register.html', {'errmsg':'数据不完整'})

    if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
        return render(request, 'register.html', {'errmsg':'邮箱不合法'})

    if allow != 'on':
        return render(request, 'register.html', {'errmsg':'请同意协议'})

    # 进行业务处理：完成用户的注册
    user = User.objects.create_user(username, email, password)

    # 返回应答,跳转到首页
    return redirect(reverse('goods:index'))


class RegisterView(View):
    '''注册'''
    def get(self, request):
        '''显示注册页面'''
        return render(request, 'register.html')

    def post(self, request):
        '''进行注册处理'''
        # 接收数据
        username = request.POST.get('user_name')
        password = request.POST.get('pwd')
        email = request.POST.get('email')
        allow = request.POST.get('allow')

        # 进行数据校验
        if not all([username, password, email]):
            # 数据不完整
            return render(request, 'register.html', {'errmsg': '数据不完整'})

        if not re.match(r'^[a-z0-9][\w.\-]*@[a-z0-9\-]+(\.[a-z]{2,5}){1,2}$', email):
            return render(request, 'register.html', {'errmsg': '邮箱不合法'})

        if allow != 'on':
            return render(request, 'register.html', {'errmsg': '请同意协议'})

        # 校验用户名是否重复
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            # 用户不存在
            user = None

        if user:
            # 用户名已存在
            return render(request, 'register.html', {'errmsg':'用户名已存在'})

        # 进行业务处理：完成用户的注册
        user = User.objects.create_user(username, email, password)
        user.is_active = 0
        user.save()

        # 给用户注册邮箱发送激活邮件
        # 激活链接中需要包含用户的身份信息 /user/active/3

        # 对用户的身份信息进行加密，生成激活token itsdangerous
        serializer = Serializer(settings.SECRET_KEY, 3600)
        info = {'confirm':user.id}
        token = serializer.dumps(info) # bytes
        token = token.decode()

        # 使用celery发送邮件
        send_register_active_email.delay(email, username, token)

        # 返回应答,跳转到首页
        return redirect(reverse('goods:index'))


class ActiveView(View):
    '''用户激活'''
    def get(self, request, token):
        '''用户激活'''
        # 解密获取用户的身份信息
        serializer = Serializer(settings.SECRET_KEY, 3600)
        try:
            info = serializer.loads(token)
            # 获取激活用户的id
            user_id = info['confirm']

            # 根据user_id获取用户信息
            user = User.objects.get(id=user_id)
            user.is_active = 1
            user.save()

            # 跳转到登录页面
            return redirect(reverse('user:login'))
        except SignatureExpired as e:
            # 激活链接已失效
            return HttpResponse('激活链接已失效')


class LoginView(View):
    '''登录'''
    def get(self, request):
        '''显示登录页面'''
        if 'username' in request.COOKIES:
            username = request.COOKIES.get('username')
            checked = 'checked'
        else:
            username = ''
            checked = ''
        # 使用模板
        return render(request, 'login.html', {'username':username, 'checked':checked})

    def post(self, request):
        '''登录校验'''
        # 接收数据
        username = request.POST.get('username')
        password = request.POST.get('pwd')

        # 数据校验
        if not all([username, password]):
            return render(request, 'login.html', {'errmsg':'数据不完整'})

        # 业务处理:登录验证
        user = authenticate(username=username, password=password)
        if user is not None:
            # 用户名密码正确
            if user.is_active:
                # 记住用户登录状态
                login(request, user)

                # 获取登录后跳转的url地址
                # 如果获取不到next,默认跳转到首页
                next_url = request.GET.get('next', reverse('goods:index'))

                # request.GET POST QueryDict
                # request.GET.get('test','default')->None

                # 跳转到首页
                response = redirect(next_url)

                # 是否需要记住用户名
                remember = request.POST.get('remember')
                if remember == 'on':
                    response.set_cookie('username', username)
                else:
                    response.delete_cookie('username')

                return response
            else:
                # 用户账户未激活
                return render(request, 'login.html', {'errmsg':'账户未激活'})
        else:
            # 用户名或密码错误
            return render(request, 'login.html', {'errmsg':'用户名或密码错误'})


class LogoutView(View):
    '''用户退出'''
    def get(self, request):
        '''退出登录'''
        # 清除session信息
        logout(request)

        # 跳转到首页
        return redirect(reverse('goods:index'))


# /user
class UserInfoView(LoginRequiredMixin, View):
    '''用户中心-信息页'''
    def get(self, request):
        '''显示'''
        # 用户个人信息
        # AnymousUser
        # User
        user = request.user
        address = Address.objects.get_default_address(user=user)

        # 用户历史浏览记录
        # 获取redis链接对象->StrictReids
        conn = get_redis_connection('default')
        list_key = 'history_%d'%user.id

        # 从redis中获取用户浏览的商品id的列表
        sku_ids = conn.lrange(list_key, 0, 4) # [3,2,1]

        # 遍历查询用户历史浏览的商品信息，追加到goods_li列表中
        goods_li = []
        for id in sku_ids:
            goods = GoodsSKU.objects.get(id=id)
            goods_li.append(goods)

        # 组织模板上下文
        context = {'page':'user', 'address':address, 'goods_li':goods_li}

        # Django还会把request.user转给模板文件
        return render(request, 'user_center_info.html', context)


# /user/order
class UserOrderView(LoginRequiredMixin, View):
    '''用户中心-订单页'''
    def get(self, request, page):
        '''显示'''
        # 获取用户的所有订单信息
        user = request.user
        orders = OrderInfo.objects.filter(user=user).order_by('-create_time')

        # 遍历获取订单商品的信息
        # OrderInfo类实例对象
        for order in orders:
            # 根据order_id获取订单商品信息
            order_skus = OrderGoods.objects.filter(order_id=order.order_id)

            # 计算商品的小计
            # OrderGoods类的实例对象
            for order_sku in order_skus:
                amount = order_sku.price*order_sku.count
                # 动态给order_sku增加一个属性amount,保存商品的小计
                order_sku.amount = amount

            # 动态给order增加一个属性status_name, 保存订单的状态标题
            order.status_name = OrderInfo.ORDER_STATUS[order.order_status]
            # 动态给order增加一个属性order_skus，保存订单商品的信息
            order.order_skus = order_skus

        # 分页
        paginator = Paginator(orders, 1)

        # 处理页码
        try:
            page = int(page)
        except Exception as e:
            page = 1

        if page > paginator.num_pages:
            page = 1

        # 获取第page页的Page对象
        order_page = paginator.page(page)

        # 控制页码的列表，最多在页面上只显示5个页码
        # 1.总页数小于5页，显示所有页码
        # 2.当前页属于前3页，显示前5页
        # 3.当前页属于后3页，显示后5页
        # 4.其他情况，显示当前页的前2页，当前页，当前页后2页
        num_pages = paginator.num_pages
        if num_pages < 5:
            pages = range(1, num_pages + 1)
        elif page <= 3:
            pages = range(1, 6)
        elif num_pages - page <= 2:
            pages = range(num_pages - 4, num_pages + 1)
        else:
            pages = range(page - 2, page + 3)

        # 组织上下文
        context = {'order_page':order_page,
                   'pages':pages,
                   'page':'order'}

        # 使用模板
        return render(request, 'user_center_order.html', context)


# /user/address
class AddressView(LoginRequiredMixin, View):
    '''用户中心-地址页'''
    def get(self, request):
        '''显示'''
        # 获取登录的用户对象
        user = request.user

        # # 获取用户的默认收货地址
        # try:
        #     address = Address.objects.get(user=user, is_default=True)
        # except Address.DoesNotExist:
        #     # 没有默认地址
        #     address = None
        address = Address.objects.get_default_address(user=user)

        return render(request, 'user_center_site.html', {'page':'address',
                                                         'address':address})

    def post(self, request):
        '''地址的添加'''
        # 接收数据
        receiver = request.POST.get('receiver')
        addr = request.POST.get('addr')
        zip_code = request.POST.get('zip_code')
        phone = request.POST.get('phone')

        # 数据校验
        if not all([receiver, addr, phone]):
            return render(request, 'user_center_site.html', {'errmsg':'数据不完整'})

        # 联系方式校验
        if not re.match(r'^1[3|4|5|7|8][0-9]{9}$', phone):
            return render(request, 'user_center_site.html', {'errmsg':'联系方式不正确'})

        # 业务处理：地址添加
        # 1.如果用户没有默认收货地址，那添加的地址作为默认地址，否则不作为默认地址

        # 获取登录的用户对象
        user = request.user
        # try:
        #     address = Address.objects.get(user=user, is_default=True)
        # except Address.DoesNotExist:
        #     # 没有默认地址
        #     address = None
        address = Address.objects.get_default_address(user=user)

        if address:
            is_default = False
        else:
            is_default = True

        # 添加地址
        Address.objects.create(user=user,
                               receiver=receiver,
                               addr=addr,
                               zip_code=zip_code,
                               phone=phone,
                               is_default=is_default)

        # 返回应答, 刷新地址页面
        return redirect(reverse('user:address')) # get









