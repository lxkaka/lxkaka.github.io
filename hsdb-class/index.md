# HSDB 告诉我们 Java 对象的内存地址


我们都知道在 Java 中类的实例都是在 heap 中分配内存，也就是说实例对象都是存储在 heap 中。那么类对象是否也存在 heap 中呢? 为了找到这个问题的答案我们使用 [HSDB(HotSpot Debugger)](http://cr.openjdk.java.net/~minqi/6830717/raw_files/new/agent/doc/) 来看看类对象的内存布局。

### 背景知识    
在此之前我们应该了解有关 Java 对象的两个重要概念 Oop 和 Klass
* Oop  
    在 Java 程序运行的过程中，每创建一个新的对象，在 JVM 内部就会相应地创建一个对应类型的 oop（普通对象指针） 对象。各种 oop 类的共同基类为 oopDesc 类。
    在 JVM 内部，一个 Java 对象在内存中的布局可以连续分成两部分：对象头（instanceOopDesc） 和实例数据（成员变量）。
    instanceOopDesc 对象头包含两部分信息：Mark Word 和 元数据指针(Klass*)：

    ```c++
    volatile markOop  _mark;
    union _metadata {
        Klass*      _klass;
        narrowKlass _compressed_klass;
    } _metadata;
    ```
* Klass
    每个Java对象的对象头里，_klass 字段会指向一个VM内部用来记录类的元数据用的 InstanceKlass 对象；InsanceKlass 里有个 _java_mirror 字段，指向该类所对应的Java镜像——java.lang.Class实例。HotSpot VM 会给 Class 对象注入一个隐藏字段 “klass”，用于指回到其对应的 InstanceKlass 对象。这样，klass 与 mirror 之间就有双向引用，可以来回导航。
    这个模型里，java.lang.Class 实例并不负责记录真正的类元数据，而只是对VM内部的 InstanceKlass 对象的一个包装供 Java 的反射访问用。

    ```
    Java object --->  InstanceKlass  <---> java.lang.Class instance(java mirror)
    [_mark]           [...]              [klass](隐藏字段)
    [_klass]          [_java_mirror] 
    [fileds]          [...]
    ```

### Java 对象探究
示例代码 

```java
public class BaseApplication {

    final static CountDownLatch cd = new CountDownLatch(10);

    private static int a = 0;

    private static class Task {
        private String b = "task";

        private void method(){
            a++;
            System.out.println(b + a);
        }
    }
    public static void main(String[] args) {
        Task task = new Task();
        task.method();
    }
}
```
#### 使用 HSDB 步骤         
* 在 method 内部打上断点，以 debug 模式运行  
* 启动 HSDB (根据自己 jdk 安装路径)    
`sudo java -cp /Library/Java/JavaVirtualMachines/jdk1.8.0_171.jdk/Contents/Home/lib/sa-jdi.jar sun.jvm.hotspot.HSDB`     
* attch to HotSpot process    
  这一步先使用 `jps` 获取到 java 进程 id    
![attach](https://pics.lxkaka.wang/attach.png)    

#### 分析 Java 对象    
进入 HSDB 后选择对应的线程，如 main 线程，然后在 *Tools* tab 里选择 *Object Histogram* 找到要分析的类    
![object](https://pics.lxkaka.wang/object.png)  

然后双击该类会看到有多少实例被创建出来，选中某一个实例 **inspect** 我们就能看到这个对象的真正在 JVM 里的构成即我们上面所说的 `Oop`      
![oop](https://pics.lxkaka.wang/oop.png)      

可以使用另外一种方式找到 Klass, 在 *Tools* tab 选择 *Class Browser* 搜索关键字          
![class-brow](https://pics.lxkaka.wang/class-browser.png)  

现在来看 `Task` 的实例内存地址  *0x00000007959380b8*，这个地址位于 JVM 中的内存模型中哪一个区域呢？  
在 *Window* 命令行中执行         
    ```
    hsdb> universe
    Heap Parameters:
    ParallelScavengeHeap [ PSYoungGen [ eden =  [0x0000000795580000,0x0000000795a14678,0x0000000797600000] , from =  [0x0000000797b00000,0x0000000797b00000,0x0000000798000000] , to =  [0x0000000797600000,0x0000000797600000,0x0000000797b00000]  ] PSOldGen [  [0x0000000740000000,0x0000000740000000,0x0000000745580000]  ]  ]
    ```

能清楚的看到实例的内存地址 *0x00000007959380b8* 在 eden 的地址范围之内，所以是实例都是在 JVM 的堆里分配内存。

#### 分析 Class 对象
以示例代码中的 `BaseApplication` 类为例，我们先找到 `InstanceKlass`，然后通过 `_java_mirror 找到 Class 对象`  
![class](https://pics.lxkaka.wang/Class.png)      
通过上图和 Class 对象的内存地址   *0x0000000795924de0* 清楚的看到 Class 对象的地址同样在 eden 的范围之内，即在堆上，并且类的静态成员变量就在 Class 对象中。

#### 指针压缩  
在上面的探究过程中，同样发现了指针压缩的证据。在分析实例对象的时候，我们知道对象头有指向 `InstanceKlass` 的指针，我们先具体看看这个指针的数据是什么样子的？     
![klass-ptr](https://pics.lxkaka.wang/klass-ptr.png)   

通过上图我们看到指针的值是 *0x00000000f800c392*, 而真实的 `InstanceKlass`的内存地址是   *0x00000007c0061c90*  
![klass-arrr](https://pics.lxkaka.wang/klass-addr.png)  

这就是指针压缩的的结果，当开启指针压缩的时候，JVM 按照8字节寻址。
`CompressedOops 转换成地址：ObjectAddress64 = BaseAddress64 + 8*CompressedOops`  
JVM 进程可以请求操作系统把堆的基址分配在虚地址为 0 的位置，那么 CompressedOops 转换成地址，就成了：`ObjectAddress64 = 8*CompressedOops`
也就是说 `InstanceKlass` 内存地址是对象中的指针左移 3 位可得(32位压缩指针能寻址2^35个字节（即32GB）的地址空间，超过 32GB 则会关闭压缩指针)。转换成二进制可以清楚的看出   
```
# 0x00000000f800c392 (左移3位得到内存地址)
11111000000000001100001110010010
# 0x00000007c0061c90 
11111000000000001100001110010010000
```  

所以，如果我们关闭指针压缩，JVM 按照1字节来寻址，那是不是 `ObjectAddress64 = CompressedOops`   
首先加上启动参数，关闭指针压缩  `-XX:-UseCompressedOops`   
通过下图我们看到确实两者一致    
![64-ptr](https://pics.lxkaka.wang/64-ptr.png)    
![64-addr](https://pics.lxkaka.wang/64-addr.png)    

