# 定义模型类对应的索引类

from haystack import indexes
# 导入对应的模型类
from goods.models import GoodsSKU


# 指定对于某个类的某些数据建立索引
# 索引类名:模型类+Index
class GoodsSKUIndex(indexes.SearchIndex, indexes.Indexable):
    # 索引字段， use_template指定根据哪些字段生成索引会放在一个文件中
    text = indexes.CharField(document=True, use_template=True)

    def get_model(self):
        # 返回你的模型类
        return GoodsSKU

    # 建立索引的数据
    def index_queryset(self, using=None):
        return self.get_model().objects.all()