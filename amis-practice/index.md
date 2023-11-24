# 高效搭建后台系统的解决方案-amis

最近需要搭建一个管理后台来给产品和运营同学使用。管理后台简单来说就是信息管理的工具需要提供增删改查的功能。从细节上来说这样的一个后台一般都会包含以下
* 可以对数据做筛选
* 有按钮可以刷新数据
* 编辑单行数据
* 批量修改和删除
* 查询某列
* 按某列排序
* 隐藏某列
* 开启整页内容拖拽排序
* 表格有分页（页数还能同步到地址栏）
* 有数据汇总
* 支持导出 Excel
* 表头有提示文字
* 鼠标移动到「平台」那列的内容时还有放大镜符号，可以展开查看更多
如果这些功能全部实现至少需要一个熟悉前端的同学花几天时间。但往往这些页面和交互都是通用的，那么有没有一种更高效的方式甚至不需要开发代码就能实现这样的页面？
答案是有，我们可以看一下 [amis](https://aisuda.bce.baidu.com/amis/zh-CN/docs/index)。

### amis 的优势
>* 提供完整的界面解决方案：其它 UI 框架必须使用 JavaScript 来组装业务逻辑，而 amis 只需 JSON 配置就能完成完整功能开发，包括数据获取、表单提交及验证等功能，做出来的页面不需要经过二次开发就能直接上线；
>* 大量内置组件（120+），一站式解决：其它 UI 框架大部分都只有最通用的组件，如果遇到一些稍微不常用的组件就得自己找第三方，而这些第三方组件往往在展现和交互上不一致，整合起来效果不好，而 amis 则内置大量组件，包括了富文本编辑器、代码编辑器、diff、条件组合、实时日志等业务组件，绝大部分中后台页面开发只需要了解 amis 就足够了；
>* 支持扩展：除了低代码模式，还可以通过 自定义组件 来扩充组件，实际上 amis 可以当成普通 UI 库来使用，实现 90% 低代码，10% 代码开发的混合模式，既提升了效率，又不失灵活性；
>* 容器支持无限级嵌套：可以通过嵌套来满足各种布局及展现需求；
>* 经历了长时间的实战考验：amis 在百度内部得到了广泛使用，在 6 年多的时间里创建了 5 万页面，从内容审核到机器管理，从数据分析到模型训练，amis 满足了各种各样的页面需求，最复杂的页面有超过 1 万行 JSON 配置。

### amis 实践
如果一个不太熟悉前端的同学看了官方文档可能还会有点懵，甚至还是不知道怎么用 amis 搭建页面。下面我们就介绍一种更直白的页面搭建方法。通过 amis 的官方文档我们知道最基本的一点通过 JSON 配置就能实现页面，所以首页我们需要一个基础应用或者说一个工程来容纳 JSON 配置。

#### 模板应用
clone https://github.com/aisuda/amis-admin  
```
# 安装依赖
npm i
# 打开服务
npm start
```
我们可以基于这样一个模板应用来搭建自己的页面, 如下图所示

![amis-admin](https://pics.lxkaka.wang/amis-admin)

每个子页面的具体 json 放到了 pages 目录，所以子页面 json 编辑就从 pages 里找到对应的 json 文件就可以了。
例如列表实例/新增 页面对应的 json 如下
```json
{
  "type": "page",
  "title": "新增",
  "remark": null,
  "toolbar": [
    {
      "type": "button",
      "actionType": "link",
      "link": "/crud/list",
      "label": "返回列表"
    }
  ],
  "body": [
    {
      "title": "",
      "type": "form",
      "redirect": "/crud/list",
      "name": "sample-edit-form",
      "api": "https://3xsw4ap8wah59.cfc-execute.bj.baidubce.com/api/amis-mock/sample",
      "controls": [
        {
          "type": "text",
          "name": "engine",
          "label": "Engine",
          "required": true,
          "inline": false,
          "description": "",
          "descriptionClassName": "help-block",
          "placeholder": "",
          "addOn": null
        },
        {
          "type": "divider"
        },
        {
          "type": "text",
          "name": "browser",
          "label": "Browser",
          "required": true
        },
        {
          "type": "divider"
        },
        {
          "type": "text",
          "name": "platform",
          "label": "Platform(s)",
          "required": true
        },
        {
          "type": "divider"
        },
        {
          "type": "text",
          "name": "version",
          "label": "Engine version"
        },
        {
          "type": "divider"
        },
        {
          "type": "text",
          "name": "grade",
          "label": "CSS grade"
        }
      ]
    }
  ]
}
```
我们至此明白了页面的搭建就是开发上面这样的 json 文件，但是写这样的 json 还是费时费力还不直观。在开始我们也提到很多页面包含的功能都是通用的的，只是不同组件的组合。所以如果有一个工具能让我们直接拖拽各种组件就能生成 json 岂不是很爽。

#### 可视化编辑器
clone https://github.com/aisuda/amis-editor-demo
```
# 按照依赖
npm i
# 开始编译
npm run dev
# 打开服务
npm start
```
本地编辑器如下所示

![amis-editor](https://pics.lxkaka.wang/amis-editor-demo)

下面我们以一个简单的例子来说明，我们实现一个列表页包含编辑和删除。
##### 新增页面
在编辑器右上角点击新增页面
如下图所示我们创建一个列表页，使用**增删改查**组件
![crud-new](https://pics.lxkaka.wang/new-page)

##### 编辑字段
![crud-edit](https://pics.lxkaka.wang/curd-edit)
这里不同字段格式可以选用不同的组件来展示，比如日期，图片，视频等等有有相应的组件可以选择。

#### 接入API
![crud-api](https://pics.lxkaka.wang/crud-api)
在 amis 里邀请 api 返回的数据格式必须是
```json
{
  "status": 0,
  "msg": "",
  "data": {
    ...其他字段
  }
}
```
我们需要根据 api 实际的返回格式做一下适配
```javascript
if (payload.status === 0) {
    payload.data.items = payload.data.story_examples ? payload.data.story_examples : []
}
return payload
```

#### 预览
![crud-preview](https://pics.lxkaka.wang/crud-preview)
预览可以实时看到页面的效果。

#### copy JSON
![crud-code](https://pics.lxkaka.wang/curd-code)
如果页面搭建完毕，可以从这里复制生成的 json 到实际的项目中。

以上就是使用 amis 搭建管理后台页面的实践介绍，可以看到整体学习成本并不高，对没有编程能力的同学来说同样适用。amis 以及编辑器还有很多很多的细节可以探索，相信在这组工具的帮助下我们都能高效搭建出不错的后台系统。
amis 对应的商业产品是爱速搭，可以高效提供企业级后台解决方案，也是不错的选择。对于有研发能力的公司同样可以在 amis 基础之上打造内部的后台搭建系统，我相信是一个降本增效的有力措施之一。




