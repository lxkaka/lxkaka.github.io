# 建立动态演示的记录


# 用[Raphaeljs](http://raphaeljs.com/)画图，细节记录
## 1. [paper.path](http://raphaeljs.com/reference.html#Paper.path)的用法
举例：用Q command  
The Q command (or q for relative points) describes a curve drawn from the current point on a path to the point (x, y) using (x1, y1) as a control point. For example, consider the following code:

`paper.path(['M', 50, 150, 'Q', 225, 20, 400, 150]);`

这样的表示方法，其中的坐标都是绝对值。
如果像这样写,则 c 后面的坐标都为相对起点的距离。 `r.path("M320,240c-50,100,50,110,0,190").attr({fill: "none", "stroke-width": 2});`  


This draws the quadratic Bézier curve shown. The equivalent path using the lowercase variant of the command would be "M 50,150 q 175,-130 350,0", where the (x, y) and (x1, y1) parameters are the relative distances from the start point (50, 100):

![示意图](https://www.packtpub.com/sites/default/files/Article-Images/9161OS_03_10.PNG)

## 2. 其他用法

* 给曲线加箭头
`r.path(['M',xS,yS,'L',x1,y1]).attr({'arrow-end': 'classic-wide-long'});`  
* 加文本  
`r.text(x,y,text).attr({'font-size': 20});`  
其他参数可参考[文档](http://raphaeljs.com/reference.html#Element.attr)  
* 画圆
`r.circle(x,y,radius).attr({fill: 'none', stroke: color, 'stroke-width': 2});`

* 把多个raphael object 放到一个类似数组的对象里面，可以一次操作多个元素。  
`paper.set();`  
例子:

```js
	var pathSet = r.set();
      if(peerChoice && peerPath){
      		pathSet.forEach(function(element,index){
           	element.remove();
             });
       } 
```
          

一个比较好的[raphael tutorial](http://cancerbero.mbarreneche.com/raphaeltut/)

# WebRTC + RLNC 分布式存储系统动态演示Demo截图
![截图1](https://pics.lxkaka.wang/屏幕快照%202015-12-16%20下午12.20.56.png)
![截图2](https://pics.lxkaka.wang/屏幕快照%202015-12-16%20下午12.21.24.png)
       
               

