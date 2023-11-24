# 外部访问 k8s 中的 kafka 集群


如果直接在云厂商提供的实例上搭建 kafka 集群可以说很简单，一般不会有什么困难。当我们选择把 kafka 部署到 k8s 里，希望利用 k8s 提供的编排能力来帮助我们更方便的管理 kafka 集群。在这种情况下部署会变得复杂起来，主要两个问题
* 有状态的服务部署
* 从 k8s 集群外访问

### zookeeper 部署
我们都知道 kafka 依赖 zk, 所以首先需要在 k8s 集群部署 zookeeper。 zookeeper 是有状态的服务，所以选择的方式是 StatefulSet + PVC。
这里我们使用的 zk 镜像是 k8s 官方的  `k8s.gcr.io/kubernetes-zookeeper:1.0-3.4.10`, 从[这里](https://github.com/kow3ns/kubernetes-zookeeper/blob/master/docker/scripts/start-zookeeper) 我们能看到，zk 在启动时候会自动创建配置文件并且根据 pod 的编号动态的把 **myid** 写入到 zk 的配置文件。 
* StatefulSet 部署
这里部署3副本的 zk 集群  
StatefulSet 部署 yaml 示例如下:    
  ```
  apiVersion: apps/v1
  kind: StatefulSet
  metadata:
    name: zookeeper
  spec:
    selector:
      matchLabels:
        app: zookeeper
    serviceName: zookeeper-hs
    replicas: 3
    updateStrategy:
      type: RollingUpdate
    podManagementPolicy: OrderedReady
    template:
      metadata:
        labels:
          app: zookeeper
      spec:
        affinity:
          podAntiAffinity:
            requiredDuringSchedulingIgnoredDuringExecution:
              - labelSelector:
                  matchExpressions:
                    - key: "app"
                      operator: In
                      values:
                        - zookeeper
                topologyKey: "kubernetes.io/hostname"
        containers:
        - name: zookeeper
          imagePullPolicy: Always
          image: "k8s.gcr.io/kubernetes-zookeeper:1.0-3.4.10"
          command:
            - sh
            - -c
            - "start-zookeeper \
                    --servers=3 \
                    --data_dir=/var/lib/zookeeper/data \
                    --data_log_dir=/var/lib/zookeeper/data/log \
                    --conf_dir=/opt/zookeeper/conf \
                    --client_port=2181 \
                    --election_port=3888 \
                    --server_port=2888 \
                    --tick_time=2000 \
                    --init_limit=10 \
                    --sync_limit=5 \
                    --heap=512M \
                    --max_client_cnxns=60 \
                    --snap_retain_count=3 \
                    --purge_interval=12 \
                    --max_session_timeout=40000 \
                    --min_session_timeout=4000 \
                    --log_level=INFO"
          ports:
            - containerPort: 2181
              name: client
            - containerPort: 2888
              name: server
            - containerPort: 3888
              name: leader-election
          volumeMounts:
          - name: zookeeper-data
            mountPath: /var/lib/zookeeper
        securityContext:
          runAsUser: 1000
          fsGroup: 1000
    volumeClaimTemplates:
    - metadata:
        name: zookeeper-data
      spec:
        accessModes: [ "ReadWriteOnce" ]
        storageClassName: alicloud-disk-efficiency
        resources:
          requests:
            storage: 20Gi
  ```

* 创建 headless service 和 service
zk 集群节点之间通过 headless service 互通，客户端访问 zk 通过 service 
headless service 和 service yaml 示例如下：  
  ```
  apiVersion: v1
  kind: Service
  metadata:
    name: zookeeper-hs
    labels:
      app: zookeeper
  spec:
    ports:
    - port: 2888
      name: server
    - port: 3888
      name: leader-election
    clusterIP: None
    selector:
      app: zookeeper
  ---
  apiVersion: v1
  kind: Service
  metadata:
    name: zookeeper
    labels:
      app: zookeeper
  spec:
    ports:
    - port: 2181
      name: zookeeper-client
    selector:
      app: zookeeper
  ```


### kafka 部署
把 kafka 部署到 k8s 后，我们肯定是通过 service 从 k8s 外部访问 kafaka。这里的 service 要么是 NodePort， 要么是  LoadBalancer 类型。我们使用的方式是 LoadBalancer。   
我们先看下面这张图，这是 kafka 在集群中的网络拓扑。当我们通过地址 12.345.67:31090 访问到 kafka 后，kafka 返回的访问地址是类似这样的 endpoint `kafka-0.kafka-hs.kafka.default.svc.cluster.local:9092`。这是 k8s 集群内部能访问的 headless service endpoint 地址，从集群外部自然使用这个地址是访问不通的。    
![k8s-kafka](https://pics.lxkaka.wang/kafka-k8s-1.jpg)      
所以，我们需要解决两个问题：
1. kafka 不同的 pod 需要不通的对外能访问的地址
2. 不能使用 kafka 默认的 `advertised.listeners` 

##### 解决方案
问题1，我们为每个 pod 创建类型是 LoadBalancer 的 service 并且监听不同的端口。这样通过 LB IP + port 就能找到特定的 kafka broker。  
service 示例如下：    
  ```
  apiVersion: v1
  kind: Service
  metadata:
    name: kafka-{index}
  spec:
    externalTrafficPolicy: Local
    type: LoadBalancer
    selector:
      statefulset.kubernetes.io/pod-name: kafka-{index}
    ports:
    - protocol: TCP
      port: {9092+index}
      targetPort: 9092
  ```

问题2，我们在容器启动的时候，执行脚本动态获取 pod 编号，生成容器需要的环境变量 **KAFKA_CFG_ADVERTISED_LISTENERS**（对应 kafka broker 的配置 `advertised.listener`）    
  ```
  HOSTNAME=`hostname -s`
  if [[ $HOSTNAME =~ (.*)-([0-9]+)$ ]]; then
    ORD=${BASH_REMATCH[2]}
    PORT=$((ORD + 9092))
    #12.345.67.8 是 LB 的 ip
    export KAFKA_CFG_ADVERTISED_LISTENERS="PLAINTEXT://12.345.67.8:$PORT"
  else
    echo "Failed to get index from hostname $HOST"
    exit 1
  fi
  ```

完整的 kafka StatefulSet 示例如下：    
  ```
  apiVersion: apps/v1
  kind: StatefulSet
  metadata:
    name: kafka
  spec:
    selector:
      matchLabels:
        app: kafka
    serviceName: kafka
    replicas: 3
    updateStrategy:
      type: RollingUpdate
    podManagementPolicy: OrderedReady
    template:
      metadata:
        labels:
          app: kafka
      spec:
        affinity:
          podAntiAffinity:
            requiredDuringSchedulingIgnoredDuringExecution:
              - labelSelector:
                  matchExpressions:
                    - key: "app"
                      operator: In
                      values:
                        - kafka
                topologyKey: "kubernetes.io/hostname"
        containers:
        - name: kafka
          command:
            - bash
            - -ec
            - |
              HOSTNAME=`hostname -s`
              if [[ $HOSTNAME =~ (.*)-([0-9]+)$ ]]; then
                ORD=${BASH_REMATCH[2]}
                PORT=$((ORD + 9092))
                export KAFKA_CFG_ADVERTISED_LISTENERS="PLAINTEXT://12.345.67.8:$PORT"
              else
                echo "Failed to get index from hostname $HOST"
                exit 1
              fi
              exec /entrypoint.sh /run.sh
          imagePullPolicy: Always
          image: "bitnami/kafka:2"
          env:
            - name: ALLOW_PLAINTEXT_LISTENER
              value: "yes"
            - name: KAFKA_CFG_ZOOKEEPER_CONNECT
              value: "zookeeper-0.zookeeper-hs:2181,zookeeper-1.zookeeper-hs:2181,zookeeper-2.zookeeper-hs:2181"
            - name: KAFKA_CFG_OFFSETS_TOPIC_REPLICATION_FACTOR
              value: "3"
            - name: KAFKA_CFG_TRANSACTION_STATE_LOG_MIN_ISR
              value: "3"
            - name: KAFKA_CFG_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
              value: "3"
          ports:
            - containerPort: 9092
          volumeMounts:
            - name: kafka-data
              mountPath: /bitnami
        securityContext:
          runAsUser: 1000
          fsGroup: 1000
    volumeClaimTemplates:
    - metadata:
        name: kafka-data
      spec:
        accessModes: [ "ReadWriteOnce" ]
        storageClassName: alicloud-disk-efficiency
        resources:
          requests:
            storage: 20Gi
  ```

最终，我们从集群外面就能通过 `12.345.67.8:9092,12.345.67.8:9093,12.345.67.8:9094`这样的地址访问到 k8s 中的 kafka 集群。

