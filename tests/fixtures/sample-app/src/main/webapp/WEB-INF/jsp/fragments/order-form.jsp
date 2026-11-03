<%@ page contentType="text/html; charset=UTF-8" pageEncoding="UTF-8" %>
<%@ taglib prefix="c" uri="jakarta.tags.core" %>
<form hx-post="/orders" hx-target="#order-form">
  <input id="name" name="name" value="<c:out value='${name}'/>">
  <button id="submit">登録</button>
  <c:if test="${not empty error}"><p class="error"><c:out value="${error}"/></p></c:if>
</form>
