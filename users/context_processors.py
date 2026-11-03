def unread_notifications(request):
    count = 0
    if request.user.is_authenticated:
        count = request.user.notifications.filter(is_read=False).count()
    return {'unread_notifications': count}
