import sys
sys.path.insert(0, r"C:\Users\lnxzf\Desktop\projects\ufo\ufo")
from review_repo import is_placeholder

q = chr(34)
t1 = 'token=' + q + '$(env_get BOT_TOKEN)' + q
t2 = 'token=' + q + '1234567890:abcdefghijKLMNOP1234567890abcde' + q
t3 = "?token='+encodeURIComponent(TOKEN)'"
print('indirection_exempt:', is_placeholder(t1))
print('literal_still_flagged:', not is_placeholder(t2))
print('js_url_arg_exempt:', is_placeholder(t3))