# Transformer 结构学习总结


<script type="text/javascript"
  src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.0/MathJax.js?config=TeX-AMS_CHTML">
</script>
<script type="text/x-mathjax-config">
  MathJax.Hub.Config({
    tex2jax: {
      inlineMath: [['$','$'], ['\\(','\\)']],
      processEscapes: true},
      jax: ["input/TeX","input/MathML","input/AsciiMath","output/CommonHTML"],
      extensions: ["tex2jax.js","mml2jax.js","asciimath2jax.js","MathMenu.js","MathZoom.js","AssistiveMML.js", "[Contrib]/a11y/accessibility-menu.js"],
      TeX: {
      extensions: ["AMSmath.js","AMSsymbols.js","noErrors.js","noUndefined.js"],
      equationNumbers: {
      autoNumber: "AMS"
      }
    }
  });
</script>

transformer 已经成了当前深度学习领域最著名的网络架构，它是各大语言模型的基石。在这篇文章里我把自己在了解 transformer 的学习资料做了一个总结，一是加深体会二是希望帮助到其他想学习的同学。
我认为最 transformer 中最关键的也是最不容易懂的部分应该就是 `multi-head attention`, 所以这部分会重点介绍。在此基础上再去理解整个架构就会比较容易。

### multi-head attention 
`multi-head attention` 是 transformer 关键组成部分，我们会重点理解这部分实现。下图是此部分的架构图

![multi-head-att-arch](https://pics.lxkaka.wang/ai/multi-head-att-arch.png)

首先拆分 V："values"，K："keys"，Q："queries"，然后线性层（图中的"linear"）来转换 "values"、"keys" 和 "queries"。接下来，计算注意力权重并重新加权 "values"，并对重新加权的 "values" 求和，然后拼接所得的总和。最后，将拼接的 "values" 传递到另一个线性层。scaled dot-product attention 就是如何具体计算这些注意力并重新加权 "values" 的问题。
"keys" 和 "queries" 相同时产生的注意力就是所谓的 "self attention"。s
我们拿这样一个句子 "Anthony Hopkins admired Michael Bay as a great director" 来作为计算 `multi-head self-attention` 的例子。在这个例子中，token 的数量是 9，每个 token 被编码为一个 512 维的嵌入向量。head 的数量是 8。在这种情况下，如下图所示，输入句子 "Anthony Hopkins admired Michael Bay as a great director" 被表示为 **9 x 512** 矩阵。首先将每个 token 拆分为 **512/8=64** 维，总共 8 个向量，如下图所示，输入矩阵被分为 8 个彩色块，都是 **9 x 64** 矩阵，但是每个矩阵都表达同一个句子。然后在 8 个 head 中独立计算输入句子的`self attention`，并根据注意力/(权重) 重新加权 "values"。之后，并将每个头加权后的 value 拼接起来。在重新加权 value 之后，每个彩色块（矩阵）的大小也不会改变。每个 head 都会比较每个子空间的 "queries" 和 "keys"。如果一个 Transformer 模型有 4 层，具有 8 头多头注意力，那么它的编码器至少有 4 x 8 = 32 个头，因此编码器学习输入的 token 在 32 种子空间上的关系。

![multi-head-att-sum](https://pics.lxkaka.wang/ai/muti-att-sum.png)

#### "values" 计算过程  
首先 每个 $$[ \cdots ]$$ 表示一个 token，实际中通常是一个嵌入向量。下图展示了 "Michael" 作为 `query` 计算 "values" 的过程。query 与"keys" (即输入句子) 进行比较，得到了注意力 (权重) 的直方图，权重之和为 1。使用刚刚计算出来的权重重新加权 "values"（还是输入句子），并对 "values" 求和。

![michael-query](https://pics.lxkaka.wang/ai/micheael-query.png)

假设与 "query" token "Michael" 相比，"keys" token "Anthony"、"Hopkins"、"admired"、"Michael"、"Bay"、"as"、"a"、"great"和"director"。分别为 0.06、0.09、0.05、0.25、0.18、0.06、0.09、0.06、0.15。在这种情况下，重新加权的 token 之和为 0.06"Anthony" + 0.09"Hopkins" + 0.05"admired" + 0.25"Michael" + 0.18"Bay" + 0.06"as" + 0.09"a" + 0.06"great" 0.15"director"，这个数字就是我们实际使用的数字。
在实际上上面的 token 就是向量，所以结果就是重新加权后的向量。
对所有 "query" 重复此过程。如下图所示，会得到 9 对重新加权的 "values" 的总和，因为使用了输入句子 "Anthony Hopkins admired Michael Bay as a great director" 的每个 token。作为 "query"。将重新加权的 "values" 的总和拼接在一起，如下图紫色矩阵所示，这就是 `multi-head attention`中的 一个 head 的输出。

![values-weight](https://pics.lxkaka.wang/ai/value-weights.png)

#### Scaled-dot product 
为了计算多头注意力，如上所示我们有 8 对 "queries"、"keys" 和 "values"，在第一部分的图中用 8 种不同的颜色展示了它们。我们在 8 个不同的 head 中独立计算注意力并重新加权 "values"，并且在每个 head 中，重新加权的 "values" 是用这个非常简单的 scaled dot-produc 公式计算的： $$Attention(\boldsymbol{Q}, \boldsymbol{K}, \boldsymbol{V}) =softmax(\frac{\boldsymbol{Q} \boldsymbol{K} ^T}{\sqrt{d}_k})\boldsymbol{V}$$ 
我们拿上面 蓝色 head 计算 `scaled dot-product`来举例。
下图左侧是 Transformer 原论文的一张图，解释了 `multi-head attention` 的一个 head。输入句子分为 8 个矩阵块，然后将这些块独立地放入 8 个头中。在一个 head 中，通过三个不同的全连接层（下图中的"Linear"）转换输入矩阵，并准备三个矩阵 Q, K, V，分别是 "queries"、"keys" 和 "values"。
如下图所示，计算 $$Attention(\boldsymbol{Q}, \boldsymbol{K}, \boldsymbol{V})$$ 实际上只是将三个相同大小的矩阵相乘（不过只有 K 被转置）。生成的 **9 x 64** 矩阵就是 head 的输出。

![scale-dot1](https://pics.lxkaka.wang/ai/scale-dot1.png)
![scale-dot2](https://pics.lxkaka.wang/ai/scale-dot2.png)


计算方式如下图所示。softmax 函数对重新缩放后的乘积 $$\frac{\boldsymbol{Q} \boldsymbol{K} ^T}{\sqrt{d}_k}$$ 的每一行进行正则化，得到的 **9 x9** 矩阵可以理解为是一种自注意力热图。  
将每个"quey"与"keys"进行比较的过程是通过向量和矩阵的简单相乘来完成的，如下图所示。可以得到每个"query"的注意力直方图，得到的 9 维向量是注意力 (权重) 的列表，也就是下图中蓝色圆圈的列表。这意味着，在 Transformer 模型中，通过计算内积来比较"query"和"key"。通过用 $$\sqrt{d_k}$$ 除以重新缩放向量并使用 `softmax` 函数对它们进行正则化后，将这些向量堆叠起来，堆叠的向量就是注意力的热图。

![scarle-dot-heat](https://pics.lxkaka.wang/ai/scale-dot-heat.png)

这就是上述蓝色 head 计算 attention(权重) 的过程。每个 head 同时执行安全相同的过程就实现了 `mutl-head attention` 计算并行。然后我们把所有 head 的输出拼接再传入线性层。

![mult-att-res](https://pics.lxkaka.wang/ai/multi-att-res.png)

在了解完 `multi-head attention` 的计算过程，我们再来从整体看一下整个 transformer 架构的几大模块。

### encoder-decoder 结构
编码部分（encoders）由多层编码器 (Encoder) 组成（Transformer 论文中使用的是 6 层编码器，这里的层数 6 并不是固定的，可以根据实验效果来修改层数）。同理，解码部分（decoders）也是由多层的解码器 (Decoder) 组成（论文里也使用了 6 层解码器）。每层编码器网络结构是一样的，每层解码器网络结构也是一样的。不同层编码器和解码器网络结构不共享参数。

![encoder-decoder-arch](https://pics.lxkaka.wang/ai/encoder-docoder.jpeg)

#### encoder
编码部分的输入文本序列经过输入处理之后得到了一个向量序列，这个向量序列将被送入第 1 层编码器，第 1 层编码器输出的同样是一个向量序列，再接着送入下一层编码器：第 1 层编码器的输入是融合位置向量的词向量，更上层编码器的输入则是上一层编码器的输出。
下图展示了向量序列在单层 encoder 中的流动：融合位置信息的词向量进入 self-attention 层，self-attention 的输出每个位置的向量再输入 FFN 神经网络得到每个位置的新向量。


![encoder](https://pics.lxkaka.wang/ai/encoder.jpeg)

##### 残差连接
计算得到 self-attention 的输出向量后，单层 encode r 里后续还有两个重要的操作：残差链接、标准化。
编码器的每个子层（Self Attention 层和 FFNN）都有一个残差连接和层标准化（layer-normalization），如下图所示。

![add&norm](https://pics.lxkaka.wang/ai/add%26norm.jpeg)

#### decoder
编码器一般有多层，第一个编码器的输入是一个序列文本，最后一个编码器输出是一组序列向量，这组序列向量会作为解码器的 K、V 输入，其中 K=V=解码器输出的序列向量表示。这些注意力向量将会输入到每个解码器的 Encoder-Decoder Attention 层，这有助于解码器把注意力集中到输入序列的合适位置，如下图所示。

![decoder](https://pics.lxkaka.wang/ai/decoder.jpeg)

解码器中的 Self Attention 层，和编码器中的 Self Attention 层的区别：  
在解码器里，Self Attention 层只允许关注到输出序列中早于当前位置之前的单词。具体做法是：在 Self Attention 分数经过 Softmax 层之前，屏蔽当前位置之后的那些位置（将 attention score 设置成-inf）。
解码器 Attention 层是使用前一层的输出来构造 Query 矩阵，而 Key 矩阵和 Value 矩阵来自于编码器最终的输出。


#### 线性层和 softmax
Decoder 最终的输出是一个向量，其中每个元素是浮点数。我们怎么把这个向量转换为单词呢？这是线性层和 softmax 完成的。  
线性层就是一个普通的全连接神经网络，可以把解码器输出的向量，映射到一个更大的向量，这个向量称为 logits 向量：假设我们的模型有 10000 个英语单词（模型的输出词汇表），此 logits 向量便会有 10000 个数字，每个数表示一个单词的分数。   
然后，Softmax 层会把这些分数转换为概率（把所有的分数转换为正数，并且加起来等于 1）。然后选择最高概率的那个数字对应的词，就是这个时间步的输出单词。

![linear-softmax](https://pics.lxkaka.wang/ai/linear-softmax.jpeg)

现在再来看这张我们经常看到的图，脑子里应该已经有了比较清晰的概念和认识，那么这篇文章的目的就达到了。

![transformer](https://pics.lxkaka.wang/ai/transformer.jpeg)

