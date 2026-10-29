# Golang 中实用的图片处理方法

当我们需要在端上展示用户上传的图片时，由于用户上传的图片尺寸各异，为了良好的视觉效果，我们必须对尺寸各异的图片做处理。在这篇文章里我们介绍一种常用的处理图片方法即图片按比例缩小。这种方法需要实现两个目的一是压缩图片，二是统一图片比例。下面是在 Golang 中的实现方式。

### 基础操作

#### 图片缩放
在 Golang 里进行图片缩放我们可以直接使用这个库 *https://github.com/nfnt/resize*
这个库提供了多种图片缩放的算法，包括以下  
* NearestNeighbor: Nearest-neighbor interpolation
* Bilinear: Bilinear interpolation
* Bicubic: Bicubic interpolation
* MitchellNetravali: Mitchell-Netravali interpolation
* Lanczos2: Lanczos resampling with a=2
* Lanczos3: Lanczos resampling with a=3  

关于几种图像缩放中的插值算法可以看这篇[文档](https://www.kancloud.cn/trent/imagesharp/100477)。  
基本使用方法
```golang
// 第一个参数为缩放后的宽度
// 第二个参数为缩放后的高度
// 第三个参数为待缩放图片
//第四个参数为使用哪种插值算法
m := resize.Resize(1000, 0, img, resize.Lanczos3)
```

#### 图片绘制
在 Golang 里我们经常使用官方库 `image/draw` 来绘制图片。
两个重要方法  
```golang
func Draw(dst Image, r image.Rectangle, src image.Image, sp image.Point, op Op)
func DrawMask(dst Image, r image.Rectangle, src image.Image, sp image.Point, mask image.Image, mp image.Point, op Op)
// dst 绘图的背景图
// r 背景图的绘图区域;
// src 要绘制的图
// sp src绘制的开始点，一般是 src 图的左上角
// op 包括 draw.Over 和 draw.Src
// op 对于没有 mask 的情况，draw.Src 和 draw.Over 一样， 意思就是 src 图片直接盖在 dst 图片上，dst 被盖住的部分是不可见的
```
关于 **draw** 的参数理解可以参考这篇[文章](https://mipsmonsta.medium.com/golang-creating-images-and-drawing-simply-explained-part-2-4cf4aad2f85b)。

### 图片按比例缩小
有了上述的背景知识后再来实现图片按特定比例缩放就容易多了。下面的代码实现是把任意一张图片按照 16:9 的比例缩小，并且对比例失调的部分用白边补齐。
```golang
// ResizeImage 图片按 16:9 缩小，白边补齐
func ResizeImage(file io.Reader) (out io.Reader, err error) {
	// file 是原图
	buffer, err := ioutil.ReadAll(file)
	if err != nil {
		return
	}
	// 检查图片类型
	fileType := http.DetectContentType(buffer)
	var img image.Image
	if fileType == "image/png" {
		// decode jpeg into image.Image
		img, err = png.Decode(bytes.NewReader(buffer))
	} else if fileType == "image/jpeg" {
		img, err = jpeg.Decode(bytes.NewReader(buffer))
	} else {
		err = errors.New("invalid file type")
		return
	}
	if err != nil {
		return
	}

	// 原图的尺寸
	width := img.Bounds().Dx()
	height := img.Bounds().Dy()
	var (
		required                 = 16 / 9
		ration                   = width / height
		newW, newH, backW, backH int
	)

	// 如果原图尺寸超过 1280 * 720 则缩小；不超过则保持原尺寸只进行白边补齐
	if ration > required {
		newH = 0
		if width > 1280 {
			newW = 1280
		} else {
			newW = width
		}
		backW = newW
		backH = backW * 9 / 16
	} else {
		newW = 0
		if newH > 720 {
			newH = 720
		} else {
			newH = height
		}
		backH = newH
		backW = backH * 16 / 9
	}

	// 图片缩小
	m := resize.Resize(uint(newW), uint(newH), img, resize.NearestNeighbor)

	// 生成背景图
	newImg := image.NewRGBA(image.Rect(0, 0, backW, backH))

	// 背景图变成白色
	c := color.RGBA{R: 0xff, G: 0xff, B: 0xff, A: 0xff}
	for x := 0; x < backW; x++ {
		for y := 0; y < backH; y++ {
			newImg.Set(x, y, c)
		}
	}

	// 在背景图上绘制缩小后的图片，实现补齐白边
	if ration > required {
		draw.Draw(newImg, image.Rectangle{Min: image.Point{Y: (backH - m.Bounds().Dy()) / 2}, Max: image.Point{X: backW, Y: (backH + m.Bounds().Dy()) / 2}}, m, m.Bounds().Min, draw.Src)
	} else {
		draw.Draw(newImg, image.Rectangle{Min: image.Point{X: (backW - m.Bounds().Dx()) / 2}, Max: image.Point{X: (backW + m.Bounds().Dx()) / 2, Y: backH}}, m, m.Bounds().Min, draw.Src)
	}

	// 编码生成图片
	outBuffer := new(bytes.Buffer)
	if err = jpeg.Encode(outBuffer, newImg, nil); err != nil {
		return
	}
	out = outBuffer
	return
}
```
效果一, 3788 * 832 图片缩小成 1280 * 720 (深色模式会对比的很清楚)

![图片缩放1](https://pics.lxkaka.wang/%E5%9B%BE%E7%89%87%E7%BC%A9%E6%94%BE%E6%95%88%E6%9E%9C1.png)   

![图片缩放1结果](https://pics.lxkaka.wang/%E5%9B%BE%E7%89%87%E7%BC%A9%E6%94%BE1%E7%BB%93%E6%9E%9C.jpeg)

效果二, 512 * 406 图片按照 16:9 比例补齐

![图片缩放2](https://pics.lxkaka.wang/%E5%9B%BE%E7%89%87%E7%BC%A9%E6%94%BE2.jpeg)  

![图片缩放2结果](https://pics.lxkaka.wang/%E5%9B%BE%E7%89%87%E7%BC%A9%E6%94%BE%E7%BB%93%E6%9E%9C2.jpeg)

希望这篇文章中在 Golang 里对图片的操作方法能给大家带来参考和提升。
