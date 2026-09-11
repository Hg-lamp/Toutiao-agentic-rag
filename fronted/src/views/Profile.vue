<template>
  <div class="profile-page">
    <van-nav-bar title="个人信息" left-arrow @click-left="$router.back()" fixed />
    <div v-if="profileReady && userInfo" class="profile-container">
      <van-cell-group inset class="avatar-group">
        <van-cell title="头像" center is-link @click="selectAvatar">
          <template #right-icon><van-image round width="56" height="56" :src="userInfo.avatar || 'https://fastly.jsdelivr.net/npm/@vant/assets/cat.jpeg'" /></template>
        </van-cell>
      </van-cell-group>
      <input ref="fileInputRef" type="file" accept="image/*" style="display:none" @change="onAvatarSelected" />
      <van-cell-group inset class="info-group">
        <van-cell title="昵称" :value="userInfo.nickname || '未设置'" is-link @click="showNicknameDialog" />
        <van-cell title="用户名" :value="userInfo.username || 'admin'" />
        <van-cell title="性别" :value="genderLabel" is-link @click="showGenderDialog" />
        <van-cell title="手机号" :value="userInfo.phone || '未绑定'" is-link @click="showPhoneDialog" />
        <van-cell title="个人简介" :value="userInfo.bio || '暂无简介'" is-link @click="showBioDialog" />
      </van-cell-group>
      <van-cell-group inset class="security-group">
        <van-cell title="修改密码" is-link @click="showPasswordConfirm" />
      </van-cell-group>
    </div>
  </div>
</template>
<script setup>
import { ref, computed, h, onMounted } from 'vue'; import { useUserStore } from '../store/user'; import { showDialog, showToast, showLoadingToast, showSuccessToast, showFailToast } from 'vant'; import { useRouter } from 'vue-router';
const router = useRouter(); const userStore = useUserStore(); const fileInputRef = ref(null); const profileReady = ref(false);
onMounted(async () => {
  if (!userStore.getLoginStatus) { router.push('/login'); return }
  try {
    const l = showLoadingToast({ message: '加载中...', forbidClick: true, duration: 0 });
    const r = await userStore.getUserInfoDetail();
    l.close();
    if (r.success) profileReady.value = true;
    else if (!r.unauthorized) showFailToast(r.message || '获取用户信息失败');
  }
  catch (e) { showToast.clear(); showToast.fail('获取用户信息失败') }
});
const userInfo = computed(() => userStore.userInfo);
const genderLabel = computed(() => { const m = { male:'男', female:'女', unknown:'保密' }; return m[userInfo.value?.gender] || '保密' });
const selectAvatar = () => fileInputRef.value?.click();
const onAvatarSelected = async (e) => { const f = e.target.files?.[0]; if (!f) return; try { const l = showLoadingToast({ message: '上传中...', forbidClick: true, duration: 0 }); const r = await userStore.uploadAvatar(f); l.close(); r.success ? showSuccessToast('头像更新成功') : showFailToast(r.message || '头像更新失败') } catch (e) { showToast.clear(); showToast.fail('头像更新失败') } e.target.value = '' };
const showNicknameDialog = () => { const v = ref(userInfo.value?.nickname || ''); showDialog({ title:'修改昵称', showCancelButton: true, message: h('div', {style:'padding:10px 0'}, [h('input', {value:v.value, onInput:e=>{v.value=e.target.value}, placeholder:'请输入昵称', style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;font-size:14px;outline:none;background:var(--bg-mid);color:var(--text-primary)'})]) }).then(async()=>{ if(!v.value.trim()){showToast('昵称不能为空');return} try{const l=showLoadingToast({message:'保存中...',forbidClick:true,duration:0});const r=await userStore.updateUserProfile({nickname:v.value.trim()});l.close();r.success?showSuccessToast('昵称修改成功'):showFailToast(r.message)}catch(e){showToast.clear();showToast.fail('修改失败')} }).catch(()=>{}) };
const showGenderDialog = () => { const g = ref(userInfo.value?.gender||'unknown'); const opts = [{label:'男',value:'male'},{label:'女',value:'female'},{label:'保密',value:'unknown'}]; showDialog({ title:'选择性别', showCancelButton:true, message:h('div',{style:'padding:5px 0'},opts.map(o=>h('div',{style:`padding:12px 10px;cursor:pointer;border-bottom:1px solid var(--border-light);${g.value===o.value?'color:var(--accent-purple);font-weight:600;':''}`,onClick:()=>{g.value=o.value}},o.label))) }).then(async()=>{ try{const l=showLoadingToast({message:'保存中...',forbidClick:true,duration:0});const r=await userStore.updateUserProfile({gender:g.value});l.close();r.success?showSuccessToast('性别修改成功'):showFailToast(r.message)}catch(e){showToast.clear();showToast.fail('修改失败')} }).catch(()=>{}) };
const showPhoneDialog = () => { const p = ref(userInfo.value?.phone||''); showDialog({ title:'修改手机号', showCancelButton:true, message:h('div',{style:'padding:10px 0'},[h('input',{value:p.value,onInput:e=>{p.value=e.target.value},placeholder:'请输入11位手机号',maxlength:11,type:'tel',style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;font-size:14px;outline:none;background:var(--bg-mid);color:var(--text-primary)'})]) }).then(async()=>{ const phone=p.value.trim(); if(phone&&!/^1\d{10}$/.test(phone)){showToast('请输入正确的手机号');return} try{const l=showLoadingToast({message:'保存中...',forbidClick:true,duration:0});const r=await userStore.updateUserProfile({phone:phone||null});l.close();r.success?showSuccessToast('手机号修改成功'):showFailToast(r.message)}catch(e){showToast.clear();showToast.fail('修改失败')} }).catch(()=>{}) };
const showBioDialog = () => { const v = ref(userInfo.value?.bio||''); showDialog({ title:'修改个人简介', showCancelButton:true, confirmButtonText:'确认', message:h('div',{style:'text-align:left;padding:10px 0'},[h('div',{style:'margin-bottom:5px;text-align:left;font-size:13px;color:var(--text-secondary)'},'个人简介：'),h('textarea',{value:v.value,onInput:e=>{v.value=e.target.value},style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;min-height:100px;resize:vertical;outline:none;background:var(--bg-mid);color:var(--text-primary)'})]) }).then(async()=>{ try{const l=showLoadingToast({message:'保存中...',forbidClick:true,duration:0});const r=await userStore.updateUserBio(v.value);l.close();r&&r.success?showSuccessToast('个人简介修改成功'):showFailToast(r&&r.message||'个人简介修改失败')}catch(e){showToast.clear();showToast.fail('个人简介修改失败')} }).catch(()=>{}) };
const showPasswordConfirm = () => { const o=ref(''),n=ref(''),c=ref(''); showDialog({ title:'修改密码', showCancelButton:true, message:h('div',{style:'padding:10px 0'},[h('div',{style:'margin-bottom:15px'},[h('div',{style:'margin-bottom:5px;font-size:13px;color:var(--text-secondary)'},'当前密码：'),h('input',{type:'password',value:o.value,onInput:e=>{o.value=e.target.value},style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;outline:none;background:var(--bg-mid);color:var(--text-primary)'})]),h('div',{style:'margin-bottom:15px'},[h('div',{style:'margin-bottom:5px;font-size:13px;color:var(--text-secondary)'},'新密码：'),h('input',{type:'password',value:n.value,onInput:e=>{n.value=e.target.value},style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;outline:none;background:var(--bg-mid);color:var(--text-primary)'})]),h('div',{style:'margin-bottom:15px'},[h('div',{style:'margin-bottom:5px;font-size:13px;color:var(--text-secondary)'},'确认密码：'),h('input',{type:'password',value:c.value,onInput:e=>{c.value=e.target.value},style:'width:100%;border:1px solid var(--border-light);border-radius:6px;padding:10px;box-sizing:border-box;outline:none;background:var(--bg-mid);color:var(--text-primary)'})])]) }).then(async()=>{ if(!o.value){showToast('请输入当前密码');return} if(!n.value){showToast('请输入新密码');return} if(n.value!==c.value){showToast('两次密码输入不一致');return} try{const l=showLoadingToast({message:'修改中...',forbidClick:true,duration:0});const r=await userStore.updatePassword(o.value,n.value);l.close();r&&r.success?showSuccessToast('密码修改成功'):showFailToast(r&&r.message||'密码修改失败')}catch(e){showToast.clear();showToast.fail('修改失败')} }).catch(()=>{}) };
</script>
<style scoped>
.profile-page { min-height: 100vh; }
.profile-container { padding-top: 56px; padding-bottom: 20px; }
.avatar-group, .info-group, .security-group { margin: 12px; }
</style>
