-- Casos que o banco local do painel não tem e que a tela precisa mostrar:
-- um alerta aberto e uma fala da IA com turno registrado. Pode rodar de novo.
--
--   docker exec -i saturday-postgres-1 psql -U saturday -d saturday_painel_dev < infra/painel_seed.sql
--
-- shortcut: usa a primeira conversa que já tem fala da IA. A oferta vigente
-- mora no checkpoint do grafo: as conversas com "confere" e "Difere da oferta"
-- (portabilidade e iCred) são do `painel_seed.py`.

insert into alertas (tipo, conversa_id, detalhe)
select 'envio_falhou', m.conversa_id, '{}'::jsonb
from mensagens m
where m.autor = 'ia'
  and not exists (select 1 from alertas where resolvido_em is null)
order by m.id
limit 1;

-- Uma consulta do iCred com pacote de dois contratos, para a ficha mostrar.
insert into consultas_icred (chave, cpf, conversa_id, estado, situacao, contratos, valido_ate)
select 'seed-icred', '00189004967', m.conversa_id, 'concluida', 'COM_OFERTA',
  '[{"tipo": "port_refin", "banco": "BMG", "taxa": "1.66", "prazo": 96, "parcela": "210.50", "liberado": "3200.00"},
    {"tipo": "novo", "banco": "iCred", "taxa": "1.80", "prazo": 84, "parcela": "98.40", "liberado": "4100.00"}]'::jsonb,
  now() + interval '15 minutes'
from mensagens m
where m.autor = 'ia'
  and not exists (select 1 from consultas_icred where chave = 'seed-icred')
order by m.id
limit 1;

with fala as (
  select id, conversa_id from mensagens
  where autor = 'ia' and turno_id is null
    and not exists (select 1 from mensagens where chave_mensagem = 'oferta')
  order by id
  limit 1
), turno as (
  insert into turnos (conversa_id, caminho, status, etapa, chamadas)
  select conversa_id, '["__start__", "present_offer"]'::jsonb, 'ok', 'oferta', '[]'::jsonb
  from fala
  returning id
)
update mensagens
set turno_id = (select id from turno), chave_mensagem = 'oferta'
where id = (select id from fala);
