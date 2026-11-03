<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8" %>
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>注文登録</title>
  <%-- Same responseHandling as docs/04: swap 422 form fragments, keep other 4xx/5xx as errors. --%>
  <meta name="htmx-config" content='{"responseHandling":[
    {"code":"204","swap":false},
    {"code":"[23]..","swap":true},
    {"code":"422","swap":true,"error":false},
    {"code":"[45]..","swap":false,"error":true},
    {"code":"...","swap":false}
  ]}'>
  <script src="/htmx.min.js"></script>
</head>
<body>
  <h1>注文登録</h1>
  <div id="order-form"><jsp:include page="/WEB-INF/jsp/fragments/order-form.jsp"/></div>
</body>
</html>
