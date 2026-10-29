# JIRA 集成单点登录系统 CAS


JIRA 是一个非常优秀的项目管理工具，可以帮助我们缺陷管理和任务追踪。关于 JIRA 这里不多做介绍。JIRA 本身有完善的账号系统，但是因为很多公司包括我们自己有自己的单点登录系统，比如我们自己搭建的 CAS。所以如果能把 JIRA 接入 CAS 才是理想的方案。这里介绍一下 JIRA 集成 CAS 的方案。

这里我们是用 docker 部署的 JIRA 7.x, 理论上 JIRA 7.x 不管是 docker 方式还是直接在宿主机上安装，我们的集成方案都是适用的。

## 集成方案

#### Step 1  
下载两个 jar 包 `cas-client-core-3.3.3.jar`, `cas-client-integration-atlassian-3.5.0-jira7.jar`.  
下载地址在[这里](https://bitbucket.org/mbrown_ascend/jira-cas-integration/downloads/)

#### Step 2  
修改 `web.xml`    
如果是直接在宿主机（linux）上安装的方式, 修改 `/opt/atlassian/jira/atlassian-jira/WEB-INF/web.xml`(默认路径)  
如果是 docker 方式， 我们可以先从容器中 copy 出 web.xml  
`docker cp container_id:/opt/atlassian/jira/atlassian-jira/WEB-INF/web.xml .`   

* 编写好如下内容  

    ```xml
    <!-- CAS:START - Java Client Filters -->
    
    <filter>
    <filter-name>CasSingleSignOutFilter</filter-name>
    <filter-class>org.jasig.cas.client.session.SingleSignOutFilter</filter-class>
    </filter>
    <filter>
    <filter-name>CasAuthenticationFilter</filter-name>
    <filter-class>org.jasig.cas.client.authentication.AuthenticationFilter</filter-class>
    <init-param>
        <param-name>casServerLoginUrl</param-name>
        <param-value> Include your CAS login here </param-value>
    </init-param>
    <init-param>
        <param-name>serverName</param-name>
        <param-value> include your JIRA url here </param-value>
    </init-param>
    </filter>
    <filter>
        <filter-name>CasValidationFilter</filter-name>
        <filter-class>org.jasig.cas.client.validation.Cas20ProxyReceivingTicketValidationFilter</filter-class>
        <init-param>
            <param-name>casServerUrlPrefix</param-name>
            <param-value>Include your CAS address</param-value>
        </init-param>
        <init-param>
            <param-name>serverName</param-name>
        <param-value>include your JIRA url here</param-value>
        </init-param>
        <init-param>
            <param-name>redirectAfterValidation</param-name>
            <param-value>true</param-value>
        </init-param>
    </filter>
    
    <!--- CAS:END -->
    ```

* 将上面的配置复制进 `web.xml` 大概380行的位置 **THIS MUST BE THE LAST FILTER IN THE DEFINED CHAIN**  的上面 
* 在大概 640行的位置
    ```xml
    <filter-mapping>
        <filter-name>login</filter-name>
        <url-pattern>/*</url-pattern>
        <dispatcher>REQUEST</dispatcher>
        <dispatcher>FORWARD</dispatcher> <!-- we want security/login to be applied after urlrewrites, for example -->
    </filter-mapping>
   ```
  在这部分的上面复制以下的配置  
    ```xml
    <!-- CAS:START - Java Client Filter Mappings -->
 
    <filter-mapping>
    <filter-name>CasSingleSignOutFilter</filter-name>
    <url-pattern>/*</url-pattern>
    </filter-mapping>
    <filter-mapping>
        <filter-name>CasAuthenticationFilter</filter-name>
        <url-pattern>/default.jsp</url-pattern>
    </filter-mapping>
    <filter-mapping>
        <filter-name>CasValidationFilter</filter-name>
        <url-pattern>/*</url-pattern>
    </filter-mapping>
    
    <!-- CAS:END -->
  ```

### Step 3  
修改 ` seraph-config.xml`  
和 `web.xml`类似，只是路径变为 `/opt/atlassian/jira/atlassian-jira/WEB-INF/classes/`

* 修改这部分内容 
  
  ```xml
  <init-param>
    <!--
      The login URL to redirect to when the user tries to access a protected resource (rather than clicking on
      an explicit login link). Most of the time, this will be the same value as 'link.login.url'.
    - if the URL is absolute (contains '://'), then redirect that URL (for SSO applications)
    - else the context path will be prepended to this URL
 
    If '${originalurl}' is present in the URL, it will be replaced with the URL that the user requested.
    This gives SSO login pages the chance to redirect to the original page
    -->
    <param-name>login.url</param-name>
    <!--<param-value>/login.jsp?os_destination=${originalurl}</param-value>-->
    <param-value>add your CAS login URL here</param-value>
  </init-param>
  <init-param>
    <!--
      the URL to redirect to when the user explicitly clicks on a login link (rather than being redirected after
      trying to access a protected resource). Most of the time, this will be the same value as 'login.url'.
    - same properties as login.url above
    -->
    <param-name>link.login.url</param-name>
    <!--<param-value>/login.jsp?os_destination=${originalurl}</param-value>-->
    <!--<param-value>/secure/Dashboard.jspa?os_destination=${originalurl}</param-value>-->
    <param-value>add your CAS login URL here</param-value>
  </init-param>
  <init-param>
    <!-- URL for logging out.
    - If relative, Seraph just redirects to this URL, which is responsible for calling Authenticator.logout().
    - If absolute (eg. SSO applications), Seraph calls Authenticator.logout() and redirects to the URL
    -->
    <param-name>logout.url</param-name>
    <!--<param-value>/secure/Logout!default.jspa</param-value>-->
    <param-value>add your CAS LOGOUT URL here</param-value>
  </init-param>
  ```

* 大概 95 行的位置注释掉 ` SSOSeraphAuthenticator` 和 `JIRASeraphAuthenticator` 的部分  
* 用下面的部分替代 `JIRASeraphAuthenticator`  
  ```xml
  <authenticator class="org.jasig.cas.client.integration.atlassian.Jira7CasAuthenticator">
        <init-param>
            <param-name>casServerUrlPrefix</param-name>
            <param-value>include your cas server here</param-value>
        </init-param>
        <init-param>
            <param-name>serverName</param-name>
            <param-value>include your JIRA server URL</param-value>
        </init-param>
  </authenticator>
  ```
### step 4  
把准备好的 jar 包和配置文件复制进 JIRA 相应的目录  
如果是宿主机安装方式直接复制即可  
我们采用 docker 安装， 所以修改一下 dockerfile 
```
COPY cas-client-core-3.3.3.jar /opt/atlassian/jira/atlassian-jira/WEB-INF/lib/
COPY cas-client-integration-atlassian-3.5.0-jira7.jar /opt/atlassian/jira/atlassian-jira/WEB-INF/lib/
COPY web.xml /opt/atlassian/jira/atlassian-jira/WEB-INF/
COPY seraph-config.xml /opt/atlassian/jira/atlassian-jira/WEB-INF/classes/
```  
至此，我们重启 JIRA 加载新的 jar 包和配置文件，JIRA 与 CAS 的集成就完成了，应该就可以用 CAS 的账号登录 JIRA。

